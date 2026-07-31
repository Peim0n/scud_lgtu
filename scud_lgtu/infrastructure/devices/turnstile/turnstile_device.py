"""Событийно-управляемая логика турникета.

Этот файл — логика устройства. Все команды живут в commands.py."""
from __future__ import annotations

from typing import Any, Optional

from scud_lgtu.domain.events import (
    AccessGranted,
    AccessDenied,
    AlarmChanged,
    DeviceCommand,
    PassageDetected,
)
from scud_lgtu.infrastructure.devices.turnstile.commands import (
    AlarmCommand,
    ClearAlarmCommand,
    CloseCommand,
    Command,
    DelayedCloseCommand,
    DenyCommand,
    LockCommand,
    OpenEntryCommand,
    OpenExitCommand,
    UnlockCommand,
    UnlockEntryCommand,
    UnlockExitCommand,
)


class TurnstileDevice:
    """Событийно-управляемый турникет.

    Принимает доменные события и возвращает команду.
    Команды живут в commands.py.
    """

    def __init__(self, auth_timeout: float, timings: dict, resolver: Any):
        self._mode = "idle"
        self.locked = False
        self._alarm = False
        self.current_token: Optional[str] = None
        self.current_user_id: Optional[int] = None

        self._resolver = resolver
        self._load_config(timings)

    def _load_config(self, timings: dict) -> None:
        """Загрузить имена выходов и тайминги через resolver."""
        self._auth_timeout = self._resolver.get_timing("business", "auth_timeout_s", timings.get("auth_timeout_s", 5.0))
        self._relay_timeout = self._resolver.get_timing("turnstile", "relay_open_duration_s", timings.get("relay_open_duration_s", 7.0))
        self._button_timeout = self._resolver.get_timing("turnstile", "button_timer_duration_s", timings.get("button_timer_duration_s", 7.0))
        self._indicator_duration = self._resolver.get_timing("business", "indicator_duration_s", timings.get("indicator_duration_s", 2.0))
        self._deny_beep_count = int(self._resolver.get_timing("business", "deny_beep_count", timings.get("deny_beep_count", 3)))
        self._deny_beep_duration = self._resolver.get_timing("business", "deny_beep_duration_s", timings.get("deny_beep_duration_s", 0.1))
        self._deny_beep_pause = self._resolver.get_timing("business", "deny_beep_pause_s", timings.get("deny_beep_pause_s", 0.1))
        self._alarm_beep_on_duration = self._resolver.get_timing("business", "alarm_beep_on_duration_s", timings.get("alarm_beep_on_duration_s", 0.5))
        self._alarm_beep_off_duration = self._resolver.get_timing("business", "alarm_beep_off_duration_s", timings.get("alarm_beep_off_duration_s", 0.5))

        # Имена выходов
        self._resolver.set_context("turnstile")
        self.entry_relay = self._resolver.resolve("entry_relay")
        self.exit_relay = self._resolver.resolve("exit_relay")
        self.main_buzzer = self._resolver.resolve("main_buzzer")
        self.entry_green = self._resolver.resolve("entry_green")
        self.entry_red = self._resolver.resolve("entry_red")
        self.exit_green = self._resolver.resolve("exit_green")
        self.exit_red = self._resolver.resolve("exit_red")

    @property
    def is_alarm_active(self) -> bool:
        return self._alarm

    @property
    def current_state_label(self) -> str:
        return self._mode

    @property
    def indicator_duration(self) -> float:
        return self._indicator_duration

    @property
    def deny_beep_count(self) -> int:
        return self._deny_beep_count

    @property
    def deny_beep_duration(self) -> float:
        return self._deny_beep_duration

    @property
    def deny_beep_pause(self) -> float:
        return self._deny_beep_pause

    @property
    def alarm_beep_on_duration(self) -> float:
        return self._alarm_beep_on_duration

    @property
    def alarm_beep_off_duration(self) -> float:
        return self._alarm_beep_off_duration

    def handle(self, event) -> Optional[Command]:
        """Обработать доменное событие и вернуть команду для исполнителя."""
        if isinstance(event, AccessGranted):
            return self._on_access_granted(event)
        if isinstance(event, AccessDenied):
            return self._on_access_denied(event)
        if isinstance(event, DeviceCommand):
            return self._on_device_command(event)
        if isinstance(event, AlarmChanged):
            return self._on_alarm_changed(event)
        if isinstance(event, PassageDetected):
            return self._on_passage_detected(event)
        return None

    def _on_access_granted(self, event: AccessGranted) -> Command:
        self.current_token = event.token
        self.current_user_id = event.user_id
        if event.direction == "entry":
            self._mode = "entry_open"
            return OpenEntryCommand(self, self._relay_timeout)
        self._mode = "exit_open"
        return OpenExitCommand(self, self._relay_timeout)

    def _on_access_denied(self, event: AccessDenied) -> Command:
        return DenyCommand(self, event.direction)

    def _on_device_command(self, event: DeviceCommand) -> Optional[Command]:
        command = event.command

        if command == "open_entry":
            if self._mode == "unlocked_exit":
                self._mode = "idle"
                return CloseCommand(self)
            if self._mode == "unlocked_entry":
                # Переключение с разблокированного входа на разовый вход
                self._mode = "entry_open"
                return OpenEntryCommand(self, self._button_timeout)
            if self._mode == "exit_open":
                # Переключение с разового выхода на разовый вход
                self._mode = "entry_open"
                return OpenEntryCommand(self, self._button_timeout)
            if self._mode == "entry_open":
                # Уже открыто на один раз в ту же сторону, обновляем таймаут
                return OpenEntryCommand(self, self._button_timeout)
            self._mode = "entry_open"
            return OpenEntryCommand(self, self._button_timeout)

        if command == "open_exit":
            if self._mode == "unlocked_entry":
                self._mode = "idle"
                return CloseCommand(self)
            if self._mode == "unlocked_exit":
                # Переключение с разблокированного выхода на разовый выход
                self._mode = "exit_open"
                return OpenExitCommand(self, self._button_timeout)
            if self._mode == "entry_open":
                # Переключение с разового входа на разовый выход
                self._mode = "exit_open"
                return OpenExitCommand(self, self._button_timeout)
            if self._mode == "exit_open":
                # Уже открыто на один раз в ту же сторону, обновляем таймаут
                return OpenExitCommand(self, self._button_timeout)
            self._mode = "exit_open"
            return OpenExitCommand(self, self._button_timeout)

        if command == "unlock_entry":
            if self._mode == "entry_open":
                # Переключение с разового входа на разблокированный вход
                self._mode = "unlocked_entry"
                return UnlockEntryCommand(self)
            if self._mode == "unlocked_exit":
                # Переключение с разблокированного выхода на разблокированный вход
                self._mode = "unlocked_entry"
                return UnlockEntryCommand(self)
            if self._mode == "unlocked_entry":
                # Уже разблокирован на вход, игнорируем
                return None
            self._mode = "unlocked_entry"
            return UnlockEntryCommand(self)

        if command == "unlock_exit":
            if self._mode == "exit_open":
                # Переключение с разового выхода на разблокированный выход
                self._mode = "unlocked_exit"
                return UnlockExitCommand(self)
            if self._mode == "unlocked_entry":
                # Переключение с разблокированного входа на разблокированный выход
                self._mode = "unlocked_exit"
                return UnlockExitCommand(self)
            if self._mode == "unlocked_exit":
                # Уже разблокирован на выход, игнорируем
                return None
            self._mode = "unlocked_exit"
            return UnlockExitCommand(self)

        if command == "start_close_timer":
            return DelayedCloseCommand(self, self._button_timeout)

        if command == "close":
            self._mode = "idle"
            return CloseCommand(self)

        if command == "lock":
            self.locked = True
            self._mode = "blocked"
            return LockCommand(self)

        if command == "unlock":
            self.locked = False
            self._mode = "idle"
            return UnlockCommand(self)

        if command == "cancel_unlock":
            self._mode = "idle"
            return CloseCommand(self)

        return None

    def _on_alarm_changed(self, event: AlarmChanged) -> Optional[Command]:
        if event.active:
            self._alarm = True
            self._mode = "alarm"
            return AlarmCommand(self)
        self._alarm = False
        self._mode = "blocked" if self.locked else "idle"
        return ClearAlarmCommand(self)

    def _on_passage_detected(self, event: PassageDetected) -> Command:
        self._mode = "idle"
        self.current_token = None
        self.current_user_id = None
        return CloseCommand(self)
