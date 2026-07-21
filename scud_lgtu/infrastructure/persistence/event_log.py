"""Адаптер журнала событий."""
import time

from scud_lgtu.infrastructure.persistence.event_store import EventStore, PassageEvent
from scud_lgtu.domain.access.ports.ports import EventLog
from scud_lgtu.domain.common.models.models import Passage
from scud_lgtu.domain.common.enums.enums import ResultEnum, DirectionEnum


class EventLogAdapter:
    """Адаптер EventStore для реализации EventLog."""

    def __init__(self, store: EventStore):
        """Инициализировать адаптер с хранилищем."""
        self._store = store

    def append(self, passage: Passage) -> None:
        """Добавить событие прохода в журнал."""
        # Преобразовать доменный Passage в инфраструктурный PassageEvent
        event = PassageEvent(
            direction=passage.direction.value,
            result=passage.result.value,
            zone=passage.zone,
            duration=passage.duration,
            token=passage.token or "",
            user_id=passage.user_id,
            stime=time.time(),
        )
        self._store.append(event)

    def flush(self) -> list[Passage]:
        """Сбросить все события и вернуть их."""
        events = self._store.flush()
        # Преобразовать PassageEvent обратно в Passage
        passages = []
        for event in events:
            passage = Passage(
                direction=DirectionEnum(event.direction),
                result=ResultEnum(event.result),
                zone=event.zone,
                duration=event.duration,
                token=event.token,
                user_id=event.user_id,
            )
            passages.append(passage)
        return passages

    def log_passage(self, zone: str, direction: str, duration: float, result: str = "pass") -> None:
        """Записать событие прохода напрямую."""
        event = PassageEvent(
            direction=direction,
            result=result,
            zone=zone,
            duration=duration
        )
        self._store.append(event)
