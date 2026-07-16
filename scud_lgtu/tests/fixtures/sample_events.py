"""Sample events for testing."""
from scud_lgtu.infrastructure.persistence.event_store import ScudEvent, EventType, EventSource


def sample_qr_event(max_id: str = "12345") -> ScudEvent:
    """Create a sample QR event."""
    return ScudEvent(
        type=EventType.QR_READ,
        source=EventSource.SERIAL,
        payload={"qr_data": "encrypted_payload", "max_id": max_id}
    )


def sample_card_event(card_data: str = "1234567890") -> ScudEvent:
    """Create a sample card event."""
    return ScudEvent(
        type=EventType.CARD_READ,
        source=EventSource.WIEGAND,
        payload={"card_data": card_data}
    )


def sample_mux_event(input_name: str = "button_1", state: int = 0) -> ScudEvent:
    """Create a sample mux event."""
    return ScudEvent(
        type=EventType.MUX_CHANGED,
        source=EventSource.MUX,
        payload={"input_name": input_name, "state": state}
    )


def sample_alarm_event(active: bool = True) -> ScudEvent:
    """Create a sample alarm event."""
    return ScudEvent(
        type=EventType.MUX_CHANGED,
        source=EventSource.MUX,
        payload={"alarm_active": active}
    )
