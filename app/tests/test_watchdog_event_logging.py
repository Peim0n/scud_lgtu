"""
Тест, что ScudEvent(type=ERROR, source=WATCHDOG) от Watchdog реально
доходит до журнала событий как системное событие (severity=critical),
а не теряется молча в LGTUApplication._convert_scud_event_to_domain.
"""
from app.application.lgtu_application import LGTUApplication
from app.infrastructure.persistence.event_store import (
    EventSource,
    EventType,
    ScudEvent,
)


class _FakePassageService:
    def __init__(self):
        self.system_events = []

    def log_system_event(self, description, severity="critical"):
        self.system_events.append((description, severity))


def _bare_application(passage_service):
    """Создать LGTUApplication без полного __init__ — только с полями,
    нужными _convert_scud_event_to_domain для этого сценария."""
    app = object.__new__(LGTUApplication)
    app._passage_service = passage_service
    app._devices = {}
    return app


def test_watchdog_error_event_is_logged_as_system_event():
    passage_service = _FakePassageService()
    app = _bare_application(passage_service)
    scud_event = ScudEvent(
        type=EventType.ERROR,
        source=EventSource.WATCHDOG,
        payload={"thread": "wiegand", "message": "thread 'wiegand' is dead and will not be restarted automatically"},
    )

    result = app._convert_scud_event_to_domain(scud_event)

    assert result is None  # нет доменного события устройства
    assert len(passage_service.system_events) == 1
    description, severity = passage_service.system_events[0]
    assert severity == "critical"
    assert "wiegand" in description
    assert "dead" in description
