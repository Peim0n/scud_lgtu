"""Адаптер журнала событий."""
import time

from app.domain.models import Passage
from app.infrastructure.persistence.event_store import EventStore, PassageEvent


class EventLogAdapter:
    """Адаптер EventStore для реализации EventLog."""

    def __init__(self, store: EventStore):
        """Инициализировать адаптер с хранилищем."""
        self._store = store

    def append(self, passage: Passage) -> None:
        """Добавить событие прохода в журнал."""
        # description — обязательное поле в event/put по ТЗ (§6.5).
        # Для события прохода формируем человекочитаемое описание.
        direction = passage.direction.value
        result = passage.result.value
        token_type = passage.token_type or ""
        token = passage.token or ""
        if token_type and token:
            description = f"Проход {direction}: {token_type}:{token} — {result}"
        else:
            description = f"Проход {direction} — {result}"

        event = PassageEvent(
            direction=direction,
            result=result,
            zone=passage.zone,
            duration=passage.duration,
            token=token,
            token_type=passage.token_type or PassageEvent.token_type,
            severity=passage.severity,
            user_id=passage.user_id,
            stime=time.time(),
            description=description,
        )
        self._store.append(event)

    def flush(self) -> list[PassageEvent]:
        """
        Сбросить все накопленные события журнала.

        Возвращает инфраструктурные ``PassageEvent`` (а не доменные
        ``Passage``), так как для отправки на бэкенд (§6.5) нужны поля
        event_id/token_type/severity, которых нет в доменной модели.
        """
        return self._store.flush()

    def requeue(self, events: list[PassageEvent]) -> None:
        """Вернуть неотправленные события обратно в хранилище (см. SyncService)."""
        self._store.requeue(events)

    def peek_next_event_id(self) -> int:
        """Следующий event_id, который будет назначен новому событию."""
        return self._store.peek_next_event_id()

    def oldest_pending_event_id(self):
        """event_id самого старого неотправленного события (или None)."""
        return self._store.oldest_pending_event_id()

    def log_passage(self, zone: str, direction: str, duration: float, result: str = "pass") -> None:
        """Записать событие прохода напрямую."""
        event = PassageEvent(
            direction=direction,
            result=result,
            zone=zone,
            duration=duration,
            description=f"Проход {direction} — {result}",
        )
        self._store.append(event)

    def log_system_event(self, description: str, severity: str = "critical") -> None:
        """
        Записать системное событие (не связанное с проходом) — например,
        обнаруженную Watchdog'ом смерть hardware-потока (п. 5.5 ТЗ:
        event_type=system). Такое событие уйдёт на бэкенд при следующей
        синхронизации точно так же, как события проходов (§6.5 ресурс event).
        """
        event = PassageEvent(
            event_type="system",
            severity=severity,
            description=description,
            stime=time.time(),
        )
        self._store.append(event)
