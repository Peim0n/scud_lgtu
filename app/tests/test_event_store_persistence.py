"""Тесты in-memory хранилища EventStore (п. 3, 5.5, 6.5 ТЗ).

Все данные хранятся только в оперативной памяти — ничего не пишется на
SD-карту (согласно ТЗ).
"""
from app.infrastructure.persistence.event_store import EventStore, PassageEvent


def _event(**overrides) -> PassageEvent:
    defaults = dict(event_type="access", direction="in", token_type="maxid", token="1", result="pass")
    defaults.update(overrides)
    return PassageEvent(**defaults)


def test_append_assigns_monotonic_event_id():
    store = EventStore()
    e1 = _event()
    e2 = _event()
    store.append(e1)
    store.append(e2)

    assert e1.event_id == 1
    assert e2.event_id == 2


def test_append_does_not_override_explicit_event_id():
    store = EventStore()
    event = _event(event_id=999)
    store.append(event)
    assert event.event_id == 999


def test_flush_clears_store_and_returns_events_in_order():
    store = EventStore()
    store.append(_event(token="a"))
    store.append(_event(token="b"))

    events = store.flush()

    assert [e.token for e in events] == ["a", "b"]
    assert store.count() == 0


def test_requeue_puts_events_back_at_front():
    store = EventStore()
    store.append(_event(token="old"))
    events = store.flush()

    store.append(_event(token="new"))
    store.requeue(events)

    remaining = store.flush()
    assert [e.token for e in remaining] == ["old", "new"]


def test_new_store_starts_empty():
    """In-memory store начинает с нуля при каждом создании."""
    store = EventStore()
    assert store.count() == 0
    assert store.peek_next_event_id() == 1


def test_event_id_counter_survives_flush():
    """Счётчик event_id не сбрасывается после flush()."""
    store = EventStore()
    store.append(_event(token="a"))
    store.flush()

    assert store.peek_next_event_id() == 2
