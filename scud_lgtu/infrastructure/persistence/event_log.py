"""Адаптер журнала событий."""
from scud_lgtu.infrastructure.persistence.event_store import EventStore, PassageEvent
from scud_lgtu.domain.access.ports.ports import EventLog
from scud_lgtu.domain.common.models.models import Passage
from scud_lgtu.domain.common.enums.enums import ResultEnum, DirectionEnum


class EventLogAdapter:
    """Adapter for EventStore to implement EventLog."""
    
    def __init__(self, store: EventStore):
        """Initialize adapter with store."""
        self._store = store
    
    def append(self, passage: Passage) -> None:
        """Append passage event to log."""
        # Convert domain Passage to infrastructure PassageEvent
        event = PassageEvent(
            direction=passage.direction.value,
            result=passage.result.value,
            zone=passage.zone,
            duration=passage.duration
        )
        self._store.append(event)
    
    def flush(self) -> list[Passage]:
        """Flush all events and return them."""
        events = self._store.flush()
        # Convert PassageEvent back to Passage
        passages = []
        for event in events:
            passage = Passage(
                direction=DirectionEnum(event.direction),
                result=ResultEnum(event.result),
                zone=event.zone,
                duration=event.duration
            )
            passages.append(passage)
        return passages
    
    def log_passage(self, zone: str, direction: str, duration: float, result: str = "pass") -> None:
        """Log passage event directly."""
        event = PassageEvent(
            direction=direction,
            result=result,
            zone=zone,
            duration=duration
        )
        self._store.append(event)
