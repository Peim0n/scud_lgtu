"""
Сервис синхронизации с бэкендом системы СКУД (п. 5.4.3 ТЗ).

Этот модуль реализует сервис для периодической синхронизации событий проходов
и обновления списка доступа с бэкендом. Служит прослойкой между доменной логикой
и инфраструктурой шлюза бэкенда.

Классы
-------
- SyncService: сервис синхронизации с бэкендом

Методы SyncService
------------------
- __init__: инициализировать сервис синхронизации с бэкендом, хранилищем событий и интервалом
- tick: периодический тик для синхронизации
- _sync: выполнить синхронизацию (выгрузка событий и обновление списка доступа)
"""
import logging
from typing import Any

logger = logging.getLogger(__name__)


class SyncService:
    def __init__(self, backend: Any, event_log: Any, access_repository: Any, sync_interval: float):
        self._backend = backend
        self._event_log = event_log
        self._access_repository = access_repository
        self._sync_interval = sync_interval
        self._last_sync = 0.0
        # Первый запрос всегда делаем с update=0 (принудительно полный
        # список) — контроллер только что запустился и не знает, актуален
        # ли локальный кэш (§5.4.3).
        self._force_full_update = True
        # Сверка локального event_id с последним подтверждённым бэкендом
        # (см. _reconcile_events) — делаем один раз при первой успешной
        # синхронизации после старта/переподключения.
        self._events_reconciled = False

    def tick(self, now: float) -> None:
        if now - self._last_sync >= self._sync_interval:
            self._sync()
            self._last_sync = now

    def force_full_update(self) -> None:
        """Запросить полный список идентификаторов при следующей синхронизации."""
        self._force_full_update = True

    def _sync(self) -> None:
        if not self._events_reconciled:
            self._reconcile_events()
        self._sync_events()
        self._sync_access_list()

    def _reconcile_events(self) -> None:
        """
        Сверить локальный счётчик ``event_id`` с последним событием,
        подтверждённым бэкендом (ресурс ``event/get``, §6.5).

        Сама передача событий идемпотентна за счёт уникального ``event_id``
        (повторная отправка безопасна, п. 3 ТЗ) — эта сверка не нужна для
        корректности отправки, а служит только для раннего обнаружения
        потери данных: если у бэкенда последний подтверждённый event_id
        меньше, чем ``event_id`` самого старого события, ещё стоящего в
        локальной очереди на отправку минус 1, значит часть событий между
        ними была потеряна (например, из-за повреждения локального
        хранилища) и восстановить их уже нельзя — это фиксируется как
        критическая ошибка в лог.
        """
        try:
            last_confirmed = self._backend.get_last_event()
        except Exception:  # noqa: BLE001
            logger.warning("SyncService: не удалось сверить event_id с бэкендом, попробуем на следующем цикле")
            return

        self._events_reconciled = True
        confirmed_event_id = last_confirmed.get("event_id", 0) if last_confirmed else 0
        oldest_pending = self._event_log.oldest_pending_event_id()

        if oldest_pending is None:
            # Очередь пуста — граница ожидаемо равна следующему счётчику.
            expected_next = self._event_log.peek_next_event_id()
            if confirmed_event_id + 1 < expected_next:
                logger.critical(
                    "SyncService: обнаружен разрыв event_id! Бэкенд подтвердил только до %s, "
                    "а локально уже назначено до %s — %s событий утеряны безвозвратно.",
                    confirmed_event_id, expected_next - 1, expected_next - 1 - confirmed_event_id,
                )
            return

        if oldest_pending > confirmed_event_id + 1:
            logger.critical(
                "SyncService: обнаружен разрыв event_id! Бэкенд подтвердил до %s, "
                "а самое старое событие в локальной очереди — %s — %s событий между ними утеряны.",
                confirmed_event_id, oldest_pending, oldest_pending - confirmed_event_id - 1,
            )
        elif oldest_pending <= confirmed_event_id:
            logger.info(
                "SyncService: бэкенд уже подтвердил событие %s из локальной очереди "
                "(повторная отправка безопасна благодаря идемпотентности по event_id)",
                oldest_pending,
            )

    def _sync_events(self) -> None:
        """Выгрузить и отправить накопленные события (идемпотентно, §3/§6.5)."""
        events = self._event_log.flush()
        if not events:
            return

        if not self._backend.is_online():
            # Бэкенд недоступен — не теряем события, кладём обратно в очередь.
            self._event_log.requeue(events)
            return

        sent_ok = self._backend.send_events(events)
        if not sent_ok:
            # send_events останавливается на первой ошибке (см. BackendClient) —
            # возвращаем всё пачкой обратно, порядок event_id сохранится.
            logger.warning("SyncService: не удалось отправить %d событий, возвращаем в очередь", len(events))
            self._event_log.requeue(events)

    def _sync_access_list(self) -> None:
        """Обновить локальный список доступа (§5.4.3)."""
        if not self._backend.is_online():
            return

        update_flag = 0 if self._force_full_update else 1
        try:
            response = self._backend.get_access_list(update=update_flag)
        except Exception:
            logger.exception("SyncService: ошибка получения списка доступа")
            return

        self._access_repository.update(response)
        self._force_full_update = False
