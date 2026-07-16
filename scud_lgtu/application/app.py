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

from scud_lgtu.infrastructure.engine import ScudEngine
from scud_lgtu.infrastructure.persistence.event_store import ScudEvent, ScudCommand, EventType, EventSource, CommandTarget, CommandAction, PassageEvent, EventStore
from scud_lgtu.infrastructure.backend.client import BackendClient
from scud_lgtu.infrastructure.cache.access_cache import LocalAccessCache
from scud_lgtu.infrastructure.serial.qr_codec import QRDecoder

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

        # Состояние реле
        self._relay_open_time: float = 0.0
        self._relay_open_duration: float = self._timings.get("relay_open_duration_s", 5.0)

        # Состояние индикаторов/пищалок
        self._indicator_mask: int = 0x0000
        self._indicator_time: float = 0.0
        self._indicator_duration: float = self._timings.get("indicator_duration_s", 0.5)

        self._beep_mask: int = 0x0000
        self._beep_time: float = 0.0
        self._beep_duration: float = self._timings.get("beep_signal_duration_s", 0.05)

        # Текущее состояние сдвигового регистра
        self._shift_state: int = 0x0000

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
                self._check_relay_timeout()
                self._check_indicator_timeout()
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
            # RED+BEEP при невалидной карте
            self._set_indicator_for_reader(reader, "denied", str(raw) if raw is not None else None)
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
            self._set_indicator_for_reader(reader, "pass", token)
        else:
            self._set_indicator_for_reader(reader, "denied", token)

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
            self._set_indicator_for_reader(reader, "pass", str(max_id))
        else:
            self._set_indicator_for_reader(reader, "denied", str(max_id))

    def _handle_input_signal(self, event: ScudEvent) -> None:
        """Обработать событие от датчиков прохода."""
        zone = event.payload.get("zone")
        direction = event.payload.get("direction")
        duration = event.payload.get("duration", 0.0)

        if direction in ("in", "out"):
            self._handle_passage(zone, direction, duration)
            # Выключить реле при проходе
            if self._relay_open_time > 0.0:
                self._close_turnstile()
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
        """Отправить команду на открытие турникета через сдвиговый регистр."""
        logger.info("Открытие турникета")
        # REL2 (bit15) для выхода - включить
        from scud_lgtu.config import load as load_config
        cfg = load_config()
        shift_pins = cfg.get("config", {}).get("shift_pins", {})
        rel2_pin = shift_pins.get("rel2", {}).get("pin", 15)
        relay_mask = 1 << rel2_pin
        self._shift_state |= relay_mask
        self._engine.send_command(
            ScudCommand(
                target=CommandTarget.SHIFT,
                action=CommandAction.WRITE_SHIFT,
                payload={"value": self._shift_state},
            )
        )
        self._relay_open_time = time.time()

    def _close_turnstile(self) -> None:
        """Выключить реле турникета."""
        logger.info("Закрытие турникета")
        from scud_lgtu.config import load as load_config
        cfg = load_config()
        shift_pins = cfg.get("config", {}).get("shift_pins", {})
        rel2_pin = shift_pins.get("rel2", {}).get("pin", 15)
        relay_mask = 1 << rel2_pin
        self._shift_state &= ~relay_mask
        self._engine.send_command(
            ScudCommand(
                target=CommandTarget.SHIFT,
                action=CommandAction.WRITE_SHIFT,
                payload={"value": self._shift_state},
            )
        )
        self._relay_open_time = 0.0

    def _check_relay_timeout(self) -> None:
        """Проверить таймаут реле и выключить если нужно."""
        if self._relay_open_time == 0.0:
            return

        if time.time() - self._relay_open_time > self._relay_open_duration:
            logger.info("Таймаут реле, выключение")
            self._close_turnstile()

    def _set_indicator(self, indicator_mask: int, beep_mask: int = 0) -> None:
        """Включить индикатор/пищалку на короткое время."""
        logger.info("Индикатор: ind=0x%04X, beep=0x%04X, current_state=0x%04X -> new_state=0x%04X",
                    indicator_mask, beep_mask, self._shift_state, self._shift_state | indicator_mask | beep_mask)
        self._shift_state |= indicator_mask | beep_mask
        self._engine.send_command(
            ScudCommand(
                target=CommandTarget.SHIFT,
                action=CommandAction.WRITE_SHIFT,
                payload={"value": self._shift_state},
            )
        )
        self._indicator_mask = indicator_mask
        self._indicator_time = time.time()
        # Пищалка управляется отдельным потоком для последовательности сигналов
        logger.info("Таймеры: ind_time=%.3f", self._indicator_time)

    def _beep_sequence(self, beep_mask: int) -> None:
        """
        Последовательность коротких сигналов пищалки при отказе в доступе.

        Количество сигналов и длительности берутся из конфигурации.
        """
        from scud_lgtu.config import load as load_config
        cfg = load_config()
        shift_pins = cfg.get("config", {}).get("shift_pins", {})
        buz_pin = shift_pins.get("buz", {}).get("pin", 8)
        beep_mask = 1 << buz_pin

        signal_duration = self._timings.get("deny_beep_duration_s", 0.1)
        signal_pause = self._timings.get("deny_beep_pause_s", 0.1)
        beep_count = self._timings.get("deny_beep_count", 3)

        logger.info("Запуск последовательности пищалки: mask=0x%04X, count=%d", beep_mask, beep_count)

        for i in range(beep_count):
            if not self._running.is_set():
                break
            # Включить на signal_duration
            self._shift_state |= beep_mask
            self._engine.send_command(
                ScudCommand(
                    target=CommandTarget.SHIFT,
                    action=CommandAction.WRITE_SHIFT,
                    payload={"value": self._shift_state},
                )
            )
            logger.info("Пищалка #%d: включено", i + 1)
            time.sleep(signal_duration)
            # Выключить на signal_pause
            self._shift_state &= ~beep_mask
            self._engine.send_command(
                ScudCommand(
                    target=CommandTarget.SHIFT,
                    action=CommandAction.WRITE_SHIFT,
                    payload={"value": self._shift_state},
                )
            )
            logger.info("Пищалка #%d: выключено", i + 1)
            if i < beep_count - 1:  # Не ждать после последнего сигнала
                time.sleep(signal_pause)

        logger.info("Последовательность пищалки завершена")

    def _check_indicator_timeout(self) -> None:
        """Проверить таймаут индикаторов и выключить если нужно."""
        if self._indicator_time == 0.0:
            return

        elapsed = time.time() - self._indicator_time
        if elapsed > self._indicator_duration:
            logger.info("Таймаут индикатора: %.3fs > %.3fs, выключение", elapsed, self._indicator_duration)
            self._shift_state &= ~self._indicator_mask
            self._engine.send_command(
                ScudCommand(
                    target=CommandTarget.SHIFT,
                    action=CommandAction.WRITE_SHIFT,
                    payload={"value": self._shift_state},
                )
            )
            self._indicator_time = 0.0

    def _set_indicator_for_reader(self, reader: str, result: str, card_data: Optional[str] = None) -> None:
        """Включить индикатор/пищалку для конкретного считывателя."""
        from scud_lgtu.config import load as load_config
        cfg = load_config()
        shift_pins = cfg.get("config", {}).get("shift_pins", {})

        if "Wiegand-1" in reader:
            if result == "pass":
                w1_green_pin = shift_pins.get("w1_green", {}).get("pin", 1)
                ind_mask = 1 << w1_green_pin
                beep_mask = 0
            else:
                w1_red_pin = shift_pins.get("w1_red", {}).get("pin", 2)
                ind_mask = 1 << w1_red_pin
                buz_pin = shift_pins.get("buz", {}).get("pin", 8)
                beep_mask = 1 << buz_pin
        elif "Wiegand-2" in reader:
            if result == "pass":
                w2_green_pin = shift_pins.get("w2_green", {}).get("pin", 9)
                ind_mask = 1 << w2_green_pin
                beep_mask = 0
            else:
                w2_red_pin = shift_pins.get("w2_red", {}).get("pin", 10)
                ind_mask = 1 << w2_red_pin
                buz_pin = shift_pins.get("buz", {}).get("pin", 8)
                beep_mask = 1 << buz_pin
        else:
            return

        self._set_indicator(ind_mask, beep_mask)

        # Если есть пищалка и это отказ - запустить последовательность синхронно
        if beep_mask and result == "denied":
            self._beep_sequence(beep_mask)

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
