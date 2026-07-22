"""Тесты конечного автомата турникета."""
import pytest
from scud_lgtu.domain.turnstile.services.turnstile import TurnstileState, TurnstileStateEnum
from scud_lgtu.domain.access.ports.ports import ConfigResolver


class MockResolver(ConfigResolver):
    def __init__(self, timings: dict):
        self._timings = timings

    def set_context(self, module_name: str) -> None:
        pass

    def resolve(self, name: str):
        return name

    def get_timing(self, module_name: str, timing_name: str, default=None):
        return self._timings.get(timing_name, default)

    def get_pin(self, module_name: str, pin_name: str) -> str:
        return pin_name


@pytest.fixture
def turnstile():
    timings = {
        "auth_timeout_s": 5.0,
        "relay_open_duration_s": 3.0,
        "button_timer_duration_s": 2.0,
        "shift_short_press_max_s": 0.5,
        "indicator_duration_s": 2.0,
        "beep_signal_duration_s": 0.05,
        "open_beep_duration_s": 0.1,
        "deny_beep_duration_s": 0.1,
        "deny_beep_pause_s": 0.1,
        "deny_beep_count": 3,
        "alarm_beep_on_duration_s": 0.5,
        "alarm_beep_off_duration_s": 0.5,
        "post_blockage_safety_s": 1.0,
    }
    return TurnstileState(auth_timeout=5.0, timings=timings, resolver=MockResolver(timings))


def test_initial_state(turnstile):
    assert turnstile.current_state == TurnstileStateEnum.IDLE


def test_open_entry_from_idle(turnstile):
    commands = turnstile.open_entry(start_timer=True)
    assert turnstile.current_state == TurnstileStateEnum.ENTRY_OPEN
    assert any(cmd.name == "entry_relay" and cmd.state for cmd in commands)


def test_open_exit_from_idle(turnstile):
    commands = turnstile.open_exit(start_timer=True)
    assert turnstile.current_state == TurnstileStateEnum.EXIT_OPEN
    assert any(cmd.name == "exit_relay" and cmd.state for cmd in commands)


def test_unlock_entry(turnstile):
    commands = turnstile.unlock_entry()
    assert turnstile.current_state == TurnstileStateEnum.UNLOCKED_ENTRY
    assert any(cmd.name == "entry_relay" and cmd.state for cmd in commands)


def test_unlock_exit_from_unlocked_entry(turnstile):
    turnstile.unlock_entry()
    commands = turnstile.unlock_exit()
    assert turnstile.current_state == TurnstileStateEnum.UNLOCKED_EXIT
    assert any(cmd.name == "exit_relay" and cmd.state for cmd in commands)


def test_close_from_entry_open(turnstile):
    turnstile.open_entry(start_timer=True)
    commands = turnstile.close()
    assert turnstile.current_state == TurnstileStateEnum.IDLE
    assert any(cmd.name == "entry_relay" and not cmd.state for cmd in commands)


def test_switch_from_entry_open_to_exit_open(turnstile):
    turnstile.open_entry(start_timer=True)
    commands = turnstile.open_exit(start_timer=False)
    assert turnstile.current_state == TurnstileStateEnum.EXIT_OPEN
    assert any(cmd.name == "entry_relay" and not cmd.state for cmd in commands)
    assert any(cmd.name == "exit_relay" and cmd.state for cmd in commands)


def test_switch_from_exit_open_to_entry_open(turnstile):
    turnstile.open_exit(start_timer=True)
    commands = turnstile.open_entry(start_timer=False)
    assert turnstile.current_state == TurnstileStateEnum.ENTRY_OPEN
    assert any(cmd.name == "exit_relay" and not cmd.state for cmd in commands)
    assert any(cmd.name == "entry_relay" and cmd.state for cmd in commands)


def test_auto_close_after_timeout(turnstile):
    turnstile.open_entry(start_timer=True)
    turnstile._open_since = 0.0
    commands = turnstile.tick(4.0)
    assert turnstile.current_state == TurnstileStateEnum.IDLE
    assert any(cmd.name == "entry_relay" and not cmd.state for cmd in commands)


def test_alarm_overrides_open(turnstile):
    turnstile.open_entry(start_timer=True)
    commands = turnstile.set_alarm()
    assert turnstile.current_state == TurnstileStateEnum.ALARM
    assert any(cmd.name == "exit_relay" and cmd.state for cmd in commands)
    assert any(cmd.name == "entry_relay" and not cmd.state for cmd in commands)


def test_clear_alarm_returns_to_idle(turnstile):
    turnstile.set_alarm()
    commands = turnstile.clear_alarm()
    assert turnstile.current_state == TurnstileStateEnum.IDLE


def test_clear_alarm_returns_to_locked(turnstile):
    turnstile.lock()
    turnstile.set_alarm()
    commands = turnstile.clear_alarm()
    assert turnstile.current_state == TurnstileStateEnum.BLOCKED


def test_deny_beep_sequence(turnstile):
    turnstile.deny_beep()
    turnstile._deny_beep_next_time = 0.0

    commands = turnstile.tick(0.1)
    assert any(cmd.name == "main_buzzer" and not cmd.state for cmd in commands)

    commands = turnstile.tick(0.2)
    assert any(cmd.name == "main_buzzer" and cmd.state for cmd in commands)
