"""
Бизнес-логика контроллера доступа.

Связывает ScudEngine (железо) с локальным кэшем разрешений
и бэкенд-синхронизацией. Принимает события, принимает решения,
управляет турникетом и журналирует.
"""

import logging
import queue
import threading
import time
from typing import Optional

from .engine import ScudEngine
from .events import ScudEvent, ScudCommand, EventType, EventSource, CommandTarget, CommandAction
from .models import PassageEvent
from .backend_client import BackendClient
from .local_access_cache import LocalAccessCache
from .event_store import EventStore
from .qr_decoder import QRDecoder
from .api_server import ApiServer

logger = logging.getLogger(__name__)


class AccessController:
    """
    Контроллер доступа.

    Запускается поверх ScudEngine и обрабатывает события от считывателей,
    датчиков прохода, кнопок тревоги и т.п.
    """

    def __init__(
        self,
        engine: ScudEngine,
        backend: Optional[BackendClient] = None,
        cache: Optional[LocalAccessCache] = None,
        store: Optional[EventStore] = None,
        timings: Optional[dict] = None,
    ):
        """Инициализировать контроллер доступа с кэшем, бэкендом и таймингами."""
        self._engine = engine
        self._backend = backend or BackendClient()
        self._cache = cache or LocalAccessCache()
        self._store = store or EventStore()
        self._qr = QRDecoder()
        self._timings = timings or {}

        # Последнее успешное разрешение прохода
        self._last_auth: Optional[dict] = None
        self._auth_timeout: float = self._timings.get("auth_timeout_s", 5.0)

        self._api: Optional[ApiServer] = None
        self._api_enabled = False

        self._event_counter = 0
        self._running = threading.Event()
        self._logic_thread: Optional[threading.Thread] = None
        self._sync_thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """Запустить ScudEngine и рабочие потоки контроллера."""
        logger.info("AccessController: запуск…")
        self._engine.start()
        self._running.set()

        self._logic_thread = threading.Thread(target=self._event_loop, name="AccessController", daemon=True)
        self._logic_thread.start()

        self._sync_thread = threading.Thread(target=self._sync_loop, name="BackendSync", daemon=True)
        self._sync_thread.start()

        if self._api_enabled and self._api is not None:
            self._api.start()

        logger.info("AccessController: запущен")

    def enable_api(self, host: str = "0.0.0.0", port: int = 8080) -> None:
        """Включить HTTP API для тестирования."""
        self._api_enabled = True
        self._api = ApiServer(self, host=host, port=port)

    def stop(self, timeout: float = 5.0) -> None:
        """Остановить API, потоки и ScudEngine."""
        logger.info("AccessController: остановка…")
        self._running.clear()

        if self._api is not None:
            self._api.stop()

        if self._logic_thread is not None and self._logic_thread.is_alive():
            self._logic_thread.join(timeout=timeout)
        if self._sync_thread is not None and self._sync_thread.is_alive():
            self._sync_thread.join(timeout=timeout)

        self._engine.stop(timeout=timeout)
        logger.info("AccessController: остановлен")

    def _next_event_id(self) -> int:
        """Получить следующий порядковый номер события."""
        self._event_counter += 1
        return self._event_counter

    def _event_loop(self) -> None:
        """Основной цикл обработки событий от ScudEngine."""
        events = self._engine.get_event_queue()
        while self._running.is_set():
            try:
                event = events.get(timeout=0.2)
            except queue.Empty:
                continue

            try:
                self._handle_event(event)
            except Exception as e:
                logger.exception("Ошибка обработки события %s: %s", event.type, e)

    def _handle_event(self, event: ScudEvent) -> None:
        """Маршрутизировать событие в нужный обработчик."""
        if event.type == EventType.CARD_READ:
            self._handle_card_read(event)
        elif event.type == EventType.SERIAL_DATA:
            self._handle_serial_data(event)
        elif event.type == EventType.INPUT_SIGNAL:
            self._handle_input_signal(event)
        elif event.type == EventType.MUX_CHANGED:
            logger.debug("MUX: %s", event.payload)
        elif event.type == EventType.ERROR:
            logger.error("Ошибка от %s: %s", event.source, event.payload)
        elif event.type == EventType.HEALTH:
            logger.info("Health: %s", event.payload)

    def _handle_card_read(self, event: ScudEvent) -> None:
        """Обработать считывание Wiegand-карты."""
        reader = event.payload.get("reader", "unknown")
        token = str(event.payload.get("card_data", ""))
        raw = event.payload.get("raw_data")
        is_valid = event.payload.get("is_valid", False)

        stime = time.time()
        event_id = self._next_event_id()

        if not is_valid or not token:
            passage = PassageEvent(
                event_id=event_id,
                stime=stime,
                token_type="cardid",
                token=str(raw) if raw is not None else token,
                result="denied",
                severity="notice",
                description=f"Невалидная карта на {reader}",
            )
            self._log_passage(passage)
            return

        # Проверяем Wiegand-карту как cardid
        allowed, user_id = self._cache.is_allowed("cardid", token)
        result = "pass" if allowed else "denied"
        severity = "info" if allowed else "notice"

        passage = PassageEvent(
            event_id=event_id,
            stime=stime,
            user_id=user_id,
            token_type="cardid",
            token=token,
            result=result,
            severity=severity,
            description=f"{'Разрешено' if allowed else 'Запрещено'} на {reader}",
        )
        self._log_passage(passage)

        if allowed:
            self._authorize(
                direction="in",
                token_type="cardid",
                token=token,
                user_id=user_id,
            )
            self._open_turnstile()

    def _authorize(
        self,
        direction: str,
        token_type: str,
        token: str,
        user_id: Optional[int] = None,
    ) -> None:
        """Запомнить успешную авторизацию для сопоставления с датчиками прохода."""
        self._last_auth = {
            "time": time.time(),
            "direction": direction,
            "used": False,
            "token_type": token_type,
            "token": token,
            "user_id": user_id,
        }

    def _handle_serial_data(self, event: ScudEvent) -> None:
        """Обработать данные из Serial-порта (QR или сырые данные)."""
        reader = event.payload.get("reader", "unknown")
        data = str(event.payload.get("data", "")).strip()

        # QR-код передаётся как URL
        if data.startswith("https://pass.lipetsk.ru/"):
            self._handle_qr_read(reader, data)
            return

        logger.debug("[%s] Serial данные: %s", reader, data)

    def _handle_qr_read(self, reader: str, url: str) -> None:
        """Обработать QR-код, полученный из Serial-данных."""
        stime = time.time()
        event_id = self._next_event_id()

        try:
            qr_fields = self._qr.decode_url(url)
        except Exception as e:
            logger.warning("QR от %s не декодирован: %s", reader, e)
            self._log_passage(
                PassageEvent(
                    event_id=event_id,
                    stime=stime,
                    token_type="maxid",
                    token=url,
                    result="denied",
                    severity="notice",
                    description=f"Невалидный QR на {reader}: {e}",
                )
            )
            return

        max_id = qr_fields.get("max_id")
        if max_id is None:
            logger.warning("QR от %s не содержит max_id", reader)
            self._log_passage(
                PassageEvent(
                    event_id=event_id,
                    stime=stime,
                    token_type="maxid",
                    token=url,
                    result="denied",
                    severity="notice",
                    description=f"QR без max_id на {reader}",
                )
            )
            return

        allowed, user_id = self._cache.is_allowed("maxid", str(max_id))
        result = "pass" if allowed else "denied"
        severity = "info" if allowed else "notice"

        self._log_passage(
            PassageEvent(
                event_id=event_id,
                stime=stime,
                user_id=user_id,
                token_type="maxid",
                token=str(max_id),
                result=result,
                severity=severity,
                description=f"{'Разрешено' if allowed else 'Запрещено'} QR на {reader}",
            )
        )

        if allowed:
            self._authorize(
                direction="in",
                token_type="maxid",
                token=str(max_id),
                user_id=user_id,
            )
            self._open_turnstile()

    def _handle_input_signal(self, event: ScudEvent) -> None:
        """Обработать событие от датчиков прохода."""
        zone = event.payload.get("zone")
        direction = event.payload.get("direction")
        duration = event.payload.get("duration", 0.0)

        if direction in ("in", "out"):
            self._handle_passage(zone, direction, duration)
        elif direction == "blockage":
            logger.warning("[PASS] Зона %s: ЗАСЛОН (%.3f с)", zone, duration)
        elif direction == "turnback":
            logger.info("[PASS] Зона %s: разворот (%.3f с)", zone, duration)
        else:
            sensor_id = event.payload.get("sensor_id")
            logger.info("Датчик %s: импульс %.3f с", sensor_id, duration)

    def _handle_passage(self, zone: str, direction: str, duration: float) -> None:
        """Определить тип прохода по последней авторизации."""
        now = time.time()
        stime = now - duration

        auth = self._last_auth
        if auth is None or (now - auth["time"] > self._auth_timeout):
            # Проход без авторизации
            result = "forced"
            severity = "warning"
            description = f"Принудительный проход {direction} в зоне {zone}"
        elif direction != auth["direction"]:
            # Проход в противоположном направлении
            result = "oncoming"
            severity = "notice"
            description = f"Встречное движение {direction} в зоне {zone}"
        elif auth["used"]:
            # Повторный проход по одному разрешению
            result = "double"
            severity = "notice"
            description = f"Двойной проход {direction} в зоне {zone}"
        else:
            # Обычный разрешённый проход
            result = "pass"
            severity = "info"
            description = f"Проход {direction} в зоне {zone}"
            auth["used"] = True

        logger.info("[PASS] %s: %s (%.3f с)", zone, result, duration)
        self._log_passage(
            PassageEvent(
                event_id=self._next_event_id(),
                stime=stime,
                ftime=now,
                direction=direction,
                token_type=auth["token_type"] if auth else "",
                token=auth["token"] if auth else "",
                user_id=auth.get("user_id") if auth else None,
                result=result,
                severity=severity,
                description=description,
            )
        )

    def _log_passage(self, passage: PassageEvent) -> None:
        """Сохранить событие прохода в EventStore и лог."""
        self._store.append(passage)
        logger.info(
            "[PASS] id=%d %s %s result=%s (%s)",
            passage.event_id,
            passage.token_type,
            passage.token,
            passage.result,
            passage.description,
        )

    def _open_turnstile(self) -> None:
        """Отправить команду на открытие турникета."""
        # TODO: заменить на реальное управление реле / сдвиговым регистром
        logger.info("Открытие турникета")
        self._engine.send_command(
            ScudCommand(
                target=CommandTarget.SHIFT,
                action=CommandAction.WRITE_SHIFT,
                payload={"value": 0x0001},
            )
        )

    def _sync_loop(self) -> None:
        """Периодическая синхронизация с бэкендом."""
        while self._running.is_set():
            try:
                if self._backend.is_online():
                    self._cache.update(self._backend.get_access_list())
                    self._backend.send_events(self._store.flush())
                else:
                    logger.debug("Бэкенд недоступен, работаем по локальному кэшу")
            except Exception as e:
                logger.exception("Ошибка синхронизации с бэкендом: %s", e)
            # Синхронизация каждые 10 минут согласно ТЗ
            self._running.wait(timeout=600)
