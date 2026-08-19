"""Unit-тесты для переходов конечного автомата турникета.

Эти тесты проверяют диаграмму состояний, хранящуюся в памяти MCP:
- Нормально закрыт (idle)
- Разовый вход (entry_open)
- Разовый выход (exit_open)
- Разблокирован на вход (unlocked_entry)
- Разблокирован на выход (unlocked_exit)
- Заблокирован (blocked)
- Пожарная тревога (alarm)
"""

import pytest

from app.domain.events import (
    AccessGranted,
    AlarmChanged,
    DeviceCommand,
    PassageDetected,
)
from app.infrastructure.config.module_resolver import ModuleResolver
from app.infrastructure.devices.turnstile.commands import (
    AlarmCommand,
    ClearAlarmCommand,
    CloseCommand,
    LockCommand,
    OpenEntryCommand,
    OpenExitCommand,
    UnlockCommand,
    UnlockEntryCommand,
    UnlockExitCommand,
)
from app.infrastructure.devices.turnstile.turnstile_device import TurnstileDevice


@pytest.fixture
def config():
    """Minimal test configuration for the turnstile device."""
    return {
        "timings": {
            "auth_timeout_s": 5.0,
            "relay_open_duration_s": 7.0,
            "button_timer_duration_s": 7.0,
            "indicator_duration_s": 2.0,
            "deny_beep_count": 3,
            "deny_beep_duration_s": 0.1,
            "deny_beep_pause_s": 0.1,
            "alarm_beep_on_duration_s": 0.5,
            "alarm_beep_off_duration_s": 0.5,
        },
        "turnstile": {
            "entry_relay": "entry_relay",
            "exit_relay": "exit_relay",
            "main_buzzer": "main_buzzer",
            "entry_green": "entry_green",
            "entry_red": "entry_red",
            "exit_green": "exit_green",
            "exit_red": "exit_red",
        },
    }


@pytest.fixture
def resolver(config):
    """Minimal config resolver for turnstile tests (no hardware required)."""
    return ModuleResolver(config)


@pytest.fixture
def device(config, resolver):
    """Fresh turnstile device in idle state."""
    return TurnstileDevice(
        auth_timeout=5.0,
        timings=config["timings"],
        resolver=resolver,
    )


def _cmd(device: TurnstileDevice, event) -> type | None:
    """Send event and return the command class (or None)."""
    command = device.handle(event)
    return type(command) if command is not None else None


class TestIdleTransitions:
    """Transitions from the normal-closed (idle) state."""

    def test_access_granted_entry_opens_entry(self, device):
        assert _cmd(device, AccessGranted(direction="entry")) is OpenEntryCommand
        assert device.current_state_label == "entry_open"

    def test_access_granted_exit_opens_exit(self, device):
        assert _cmd(device, AccessGranted(direction="exit")) is OpenExitCommand
        assert device.current_state_label == "exit_open"

    def test_device_command_open_entry(self, device):
        assert _cmd(device, DeviceCommand(command="open_entry")) is OpenEntryCommand
        assert device.current_state_label == "entry_open"

    def test_device_command_open_exit(self, device):
        assert _cmd(device, DeviceCommand(command="open_exit")) is OpenExitCommand
        assert device.current_state_label == "exit_open"

    def test_device_command_unlock_entry(self, device):
        assert _cmd(device, DeviceCommand(command="unlock_entry")) is UnlockEntryCommand
        assert device.current_state_label == "unlocked_entry"

    def test_device_command_unlock_exit(self, device):
        assert _cmd(device, DeviceCommand(command="unlock_exit")) is UnlockExitCommand
        assert device.current_state_label == "unlocked_exit"

    def test_device_command_lock_blocks(self, device):
        assert _cmd(device, DeviceCommand(command="lock")) is LockCommand
        assert device.current_state_label == "blocked"
        assert device.locked is True

    def test_alarm_activates(self, device):
        assert _cmd(device, AlarmChanged(active=True)) is AlarmCommand
        assert device.current_state_label == "alarm"
        assert device.is_alarm_active is True


class TestEntryOpenTransitions:
    """Transitions from the single-entry (entry_open) state."""

    @pytest.fixture
    def entry_open(self, device):
        device.handle(DeviceCommand(command="open_entry"))
        assert device.current_state_label == "entry_open"
        return device

    def test_passage_detected_closes(self, entry_open):
        assert _cmd(entry_open, PassageDetected(direction="in", zone="z1", duration=1.0)) is CloseCommand
        assert entry_open.current_state_label == "idle"

    def test_open_entry_refreshes(self, entry_open):
        # При повторном нажатии возвращается та же команда для обновления таймера
        cmd = _cmd(entry_open, DeviceCommand(command="open_entry"))
        assert cmd is not None  # Команда возвращается для обновления таймера
        assert entry_open.current_state_label == "entry_open"

    def test_open_exit_switches_to_exit(self, entry_open):
        assert _cmd(entry_open, DeviceCommand(command="open_exit")) is OpenExitCommand
        assert entry_open.current_state_label == "exit_open"

    def test_unlock_entry_switches_to_unlocked(self, entry_open):
        assert _cmd(entry_open, DeviceCommand(command="unlock_entry")) is UnlockEntryCommand
        assert entry_open.current_state_label == "unlocked_entry"

    def test_unlock_exit_switches_to_unlocked(self, entry_open):
        assert _cmd(entry_open, DeviceCommand(command="unlock_exit")) is UnlockExitCommand
        assert entry_open.current_state_label == "unlocked_exit"

    def test_close_returns_idle(self, entry_open):
        assert _cmd(entry_open, DeviceCommand(command="close")) is CloseCommand
        assert entry_open.current_state_label == "idle"

    def test_lock_is_ignored_while_passing(self, entry_open):
        assert _cmd(entry_open, DeviceCommand(command="lock")) is None
        assert entry_open.current_state_label == "entry_open"

    def test_alarm_from_entry_open(self, entry_open):
        assert _cmd(entry_open, AlarmChanged(active=True)) is AlarmCommand
        assert entry_open.current_state_label == "alarm"


class TestExitOpenTransitions:
    """Transitions from the single-exit (exit_open) state."""

    @pytest.fixture
    def exit_open(self, device):
        device.handle(DeviceCommand(command="open_exit"))
        assert device.current_state_label == "exit_open"
        return device

    def test_passage_detected_closes(self, exit_open):
        assert _cmd(exit_open, PassageDetected(direction="out", zone="z1", duration=1.0)) is CloseCommand
        assert exit_open.current_state_label == "idle"

    def test_open_exit_refreshes(self, exit_open):
        # При повторном нажатии возвращается та же команда для обновления таймера
        cmd = _cmd(exit_open, DeviceCommand(command="open_exit"))
        assert cmd is not None  # Команда возвращается для обновления таймера
        assert exit_open.current_state_label == "exit_open"

    def test_open_entry_switches_to_entry(self, exit_open):
        assert _cmd(exit_open, DeviceCommand(command="open_entry")) is OpenEntryCommand
        assert exit_open.current_state_label == "entry_open"

    def test_unlock_exit_switches_to_unlocked(self, exit_open):
        assert _cmd(exit_open, DeviceCommand(command="unlock_exit")) is UnlockExitCommand
        assert exit_open.current_state_label == "unlocked_exit"

    def test_unlock_entry_switches_to_unlocked(self, exit_open):
        assert _cmd(exit_open, DeviceCommand(command="unlock_entry")) is UnlockEntryCommand
        assert exit_open.current_state_label == "unlocked_entry"

    def test_close_returns_idle(self, exit_open):
        assert _cmd(exit_open, DeviceCommand(command="close")) is CloseCommand
        assert exit_open.current_state_label == "idle"

    def test_lock_is_ignored_while_passing(self, exit_open):
        assert _cmd(exit_open, DeviceCommand(command="lock")) is None
        assert exit_open.current_state_label == "exit_open"

    def test_alarm_from_exit_open(self, exit_open):
        assert _cmd(exit_open, AlarmChanged(active=True)) is AlarmCommand
        assert exit_open.current_state_label == "alarm"


class TestUnlockedEntryTransitions:
    """Transitions from the continuously unlocked entry state."""

    @pytest.fixture
    def unlocked_entry(self, device):
        device.handle(DeviceCommand(command="unlock_entry"))
        assert device.current_state_label == "unlocked_entry"
        return device

    def test_open_entry_returns_to_single_entry(self, unlocked_entry):
        assert _cmd(unlocked_entry, DeviceCommand(command="open_entry")) is OpenEntryCommand
        assert unlocked_entry.current_state_label == "entry_open"

    def test_open_exit_closes(self, unlocked_entry):
        assert _cmd(unlocked_entry, DeviceCommand(command="open_exit")) is CloseCommand
        assert unlocked_entry.current_state_label == "idle"

    def test_unlock_exit_switches_direction(self, unlocked_entry):
        assert _cmd(unlocked_entry, DeviceCommand(command="unlock_exit")) is UnlockExitCommand
        assert unlocked_entry.current_state_label == "unlocked_exit"

    def test_close_returns_idle(self, unlocked_entry):
        assert _cmd(unlocked_entry, DeviceCommand(command="close")) is CloseCommand
        assert unlocked_entry.current_state_label == "idle"

    def test_cancel_unlock_returns_idle(self, unlocked_entry):
        assert _cmd(unlocked_entry, DeviceCommand(command="cancel_unlock")) is CloseCommand
        assert unlocked_entry.current_state_label == "idle"

    def test_lock_blocks(self, unlocked_entry):
        assert _cmd(unlocked_entry, DeviceCommand(command="lock")) is LockCommand
        assert unlocked_entry.current_state_label == "blocked"

    def test_alarm_from_unlocked_entry(self, unlocked_entry):
        assert _cmd(unlocked_entry, AlarmChanged(active=True)) is AlarmCommand
        assert unlocked_entry.current_state_label == "alarm"


class TestUnlockedExitTransitions:
    """Transitions from the continuously unlocked exit state."""

    @pytest.fixture
    def unlocked_exit(self, device):
        device.handle(DeviceCommand(command="unlock_exit"))
        assert device.current_state_label == "unlocked_exit"
        return device

    def test_open_exit_returns_to_single_exit(self, unlocked_exit):
        assert _cmd(unlocked_exit, DeviceCommand(command="open_exit")) is OpenExitCommand
        assert unlocked_exit.current_state_label == "exit_open"

    def test_open_entry_closes(self, unlocked_exit):
        assert _cmd(unlocked_exit, DeviceCommand(command="open_entry")) is CloseCommand
        assert unlocked_exit.current_state_label == "idle"

    def test_unlock_entry_switches_direction(self, unlocked_exit):
        assert _cmd(unlocked_exit, DeviceCommand(command="unlock_entry")) is UnlockEntryCommand
        assert unlocked_exit.current_state_label == "unlocked_entry"

    def test_close_returns_idle(self, unlocked_exit):
        assert _cmd(unlocked_exit, DeviceCommand(command="close")) is CloseCommand
        assert unlocked_exit.current_state_label == "idle"

    def test_cancel_unlock_returns_idle(self, unlocked_exit):
        assert _cmd(unlocked_exit, DeviceCommand(command="cancel_unlock")) is CloseCommand
        assert unlocked_exit.current_state_label == "idle"

    def test_lock_blocks(self, unlocked_exit):
        assert _cmd(unlocked_exit, DeviceCommand(command="lock")) is LockCommand
        assert unlocked_exit.current_state_label == "blocked"

    def test_alarm_from_unlocked_exit(self, unlocked_exit):
        assert _cmd(unlocked_exit, AlarmChanged(active=True)) is AlarmCommand
        assert unlocked_exit.current_state_label == "alarm"


class TestBlockedTransitions:
    """Transitions from the admin-locked (blocked) state."""

    @pytest.fixture
    def blocked(self, device):
        device.handle(DeviceCommand(command="lock"))
        assert device.current_state_label == "blocked"
        assert device.locked is True
        return device

    def test_unlock_returns_idle(self, blocked):
        assert _cmd(blocked, DeviceCommand(command="unlock")) is UnlockCommand
        assert blocked.current_state_label == "idle"
        assert blocked.locked is False

    def test_repeated_lock_ignored(self, blocked):
        assert _cmd(blocked, DeviceCommand(command="lock")) is None
        assert blocked.current_state_label == "blocked"

    def test_alarm_from_blocked(self, blocked):
        assert _cmd(blocked, AlarmChanged(active=True)) is AlarmCommand
        assert blocked.current_state_label == "alarm"


class TestAlarmTransitions:
    """Transitions involving the fire-alarm state."""

    @pytest.fixture
    def alarm(self, device):
        device.handle(AlarmChanged(active=True))
        assert device.current_state_label == "alarm"
        return device

    def test_clear_alarm_returns_idle(self, alarm):
        assert _cmd(alarm, AlarmChanged(active=False)) is ClearAlarmCommand
        assert alarm.current_state_label == "idle"
        assert alarm.is_alarm_active is False

    def test_clear_alarm_returns_blocked_when_locked(self, alarm):
        alarm.locked = True
        command = alarm.handle(AlarmChanged(active=False))
        assert isinstance(command, ClearAlarmCommand)

        class _MockExecutor:
            def __init__(self):
                self.commands = []

            async def apply(self, cmds):
                self.commands.extend(cmds)

        executor = _MockExecutor()
        import asyncio
        asyncio.run(command.run(executor))

        assert alarm.current_state_label == "blocked"
        assert alarm.is_alarm_active is False

    def test_lock_ignored_during_alarm(self, alarm):
        assert _cmd(alarm, DeviceCommand(command="lock")) is None
        assert alarm.current_state_label == "alarm"


class TestLockGuard:
    """If the locked flag is set while in idle, next event forces blocked state."""

    def test_any_event_enforces_blocked_when_locked_flag_set(self, device):
        device.locked = True
        assert _cmd(device, DeviceCommand(command="open_entry")) is LockCommand
        assert device.current_state_label == "blocked"
