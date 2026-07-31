"""Событийно-управляемая логика турникета.

Этот файл — логика устройства. Все команды живут в commands.py."""
from __future__ import annotations

from typing import Any, Optional

from scud_lgtu.domain.access_device import AccessDevice
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


class TurnstileDevice(AccessDevice):
    """Событийно-управляемый турникет.

    Принимает доменные события и возвращает команду.
    Команды живут в commands.py.
    """

    def __init__(self, auth_timeout: float, timings: dict, resolver: Any):
        super().__init__(device_id="turnstile", timings=timings, resolver=resolver)
        self._mode = "idle"
        self._alarm = False
        self.current_token: Optional[str] = None
        self.current_user_id: Optional[int] = None
        self._auth_timeout = auth_timeout

    def _load_config(self, timings: dict) -> None:
        """Загрузить тайминги через базовый класс и специфичные для турникета."""
        super()._load_config(timings)
        self._auth_timeout = self._resolver.get_timing("business", "auth_timeout_s", timings.get("auth_timeout_s", 5.0))

    def _load_io_mappings(self) -> None:
        """Загрузить имена выходов турникета."""
        # Временно используем старый путь для обратной совместимости с текущим конфигом
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
        # Если установлена админская блокировка, сначала переводим в blocked,
        # кроме случаев, когда уже заблокированы или активна тревога.
        # Обработка самого AlarmChanged идёт без этого guard.
        if not isinstance(event, AlarmChanged):
            if self.locked and self._mode not in ("blocked", "alarm"):
                self._mode = "blocked"
                return LockCommand(self)

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
            if self._mode == "unlocked_entry":
                # Короткий Shift из разблокированного входа
                self._mode = "idle"
                return CloseCommand(self)
            if self._mode == "unlocked_exit":
                # Короткий Shift из разблокированного выхода
                self._mode = "idle"
                return CloseCommand(self)
            self._mode = "idle"
            return CloseCommand(self)

        if command == "lock":
            if self._mode == "blocked":
                # Уже заблокирован, игнорируем
                return None
            if self._mode in ("entry_open", "exit_open", "alarm"):
                # Не блокируем, пока человек может проходить или активна тревога
                return None
            # idle / unlocked_entry / unlocked_exit
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
        # Диаграмма: после отмены ОПС всегда возвращаемся в нормально закрыт.
        # Если установлен флаг админской блокировки, следующая проверка переведёт
        # устройство в blocked через handle().
        self._mode = "idle"
        return ClearAlarmCommand(self)

    def _on_passage_detected(self, event: PassageDetected) -> Command:
        self._mode = "idle"
        self.current_token = None
        self.current_user_id = None
        return CloseCommand(self)
