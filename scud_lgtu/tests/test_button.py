from unittest.mock import Mock

import scud_lgtu.application.handlers.button as button_handler
from scud_lgtu.application.handlers.button import handle_button_pressed
from scud_lgtu.domain.common.events.events import ButtonPressed


DEVICES = {
    "buttons": {
        "entry": {"label": "button_1", "action": "open_entry"},
        "shift": {"label": "button_3", "action": "shift"},
    }
}


def setup_function():
    button_handler._shift_state.update(pressed=False, used=False)
    button_handler._button_pressed_at.clear()


def test_short_button_pulse_is_ignored(monkeypatch):
    turnstile = Mock()
    event_bus = Mock()
    times = iter((1.0, 1.04))
    monkeypatch.setattr(button_handler, "monotonic", lambda: next(times))

    handle_button_pressed(ButtonPressed("button_1", True), turnstile, event_bus, DEVICES, 0.05)
    handle_button_pressed(ButtonPressed("button_1", False), turnstile, event_bus, DEVICES, 0.05)

    turnstile.open_entry.assert_not_called()
    event_bus.publish.assert_not_called()


def test_valid_button_press_runs_action_on_release(monkeypatch):
    turnstile = Mock()
    turnstile.current_state = None
    turnstile.open_entry.return_value = [Mock()]
    event_bus = Mock()
    times = iter((1.0, 1.05))
    monkeypatch.setattr(button_handler, "monotonic", lambda: next(times))

    handle_button_pressed(ButtonPressed("button_1", True), turnstile, event_bus, DEVICES, 0.05)
    handle_button_pressed(ButtonPressed("button_1", False), turnstile, event_bus, DEVICES, 0.05)

    turnstile.open_entry.assert_called_once_with(start_timer=False)
    turnstile.start_open_timer.assert_called_once()
    event_bus.publish.assert_called_once()


def test_short_shift_pulse_is_ignored(monkeypatch):
    turnstile = Mock()
    event_bus = Mock()
    times = iter((1.0, 1.04))
    monkeypatch.setattr(button_handler, "monotonic", lambda: next(times))

    handle_button_pressed(ButtonPressed("button_3", True), turnstile, event_bus, DEVICES, 0.05)
    handle_button_pressed(ButtonPressed("button_3", False), turnstile, event_bus, DEVICES, 0.05)

    turnstile.close.assert_not_called()
