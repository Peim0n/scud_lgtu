"""Событийно-управляемая логика турникета.

Этот файл — логика устройства. Все команды живут в commands.py."""
from __future__ import annotations

import logging
from typing import Any

from app.domain.access_device import AccessDevice
from app.domain.commands import Command
from app.domain.events import (
    AccessDenied,
    AccessGranted,
    AlarmChanged,
    DeviceCommand,
    PassageDetected,
)
from app.infrastructure.devices.turnstile.commands import (
    AlarmCommand,
    ClearAlarmCommand,
    CloseCommand,
    DelayedCloseCommand,
    DenyCommand,
    LockCommand,
    OpenEntryCommand,
    OpenExitCommand,
    UnlockCommand,
    UnlockEntryCommand,
    UnlockExitCommand,
)

logger = logging.getLogger(__name__)


class TurnstileDevice(AccessDevice):
    """Событийно-управляемый турникет.

    Принимает доменные события и возвращает команду.
    Команды живут в commands.py.
    """

    def __init__(self, auth_timeout: float, timings: dict, resolver: Any):
        super().__init__(device_id="turnstile", timings=timings, resolver=resolver)
        self._mode = "idle"
        self._alarm = False
        self.current_token: str | None = None
        self.current_user_id: int | None = None
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

    @property
    def open_beep_duration(self) -> float:
        return self._open_beep_duration

    @property
    def output_names(self) -> tuple[str, ...]:
        return (
            self.entry_relay,
            self.exit_relay,
            self.main_buzzer,
            self.entry_green,
            self.entry_red,
            self.exit_green,
            self.exit_red,
        )

    def is_equivalent_state(self, old_state: str, new_state: str) -> bool:
        if old_state == new_state:
            return True
        equivalents = {
            "entry_open": {"unlocked_entry"},
            "unlocked_entry": {"entry_open"},
            "exit_open": {"unlocked_exit"},
            "unlocked_exit": {"exit_open"},
        }
        return new_state in equivalents.get(old_state, set())

    def handle(self, event) -> Command | None:
        """Обработать доменное событие и вернуть команду для исполнителя."""
        # Если установлена админская блокировка, сначала переводим в blocked,
        # кроме случаев, когда уже заблокированы или активна тревога.
        # Обработка самого AlarmChanged идёт без этого guard.
        if (
            not isinstance(event, AlarmChanged)
            and self.locked
            and self._mode not in ("blocked", "alarm")
        ):
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

    def _on_access_granted(self, event: AccessGranted) -> Command | None:
        self.current_token = event.token
        self.current_user_id = event.user_id
        if event.direction == "entry":
            if self._mode == "entry_open":
                # Уже открыто на вход, просто обновляем таймер
                return OpenEntryCommand(self, self._relay_timeout)
            if self._mode == "unlocked_entry":
                # Уже разблокирован на вход, игнорируем
                return None
            self._mode = "entry_open"
            logger.info(f"[TurnstileDevice] mode={self._mode}, token={event.token}, user_id={event.user_id}")
            return OpenEntryCommand(self, self._relay_timeout)
        if self._mode == "exit_open":
            # Уже открыто на выход, просто обновляем таймер
            return OpenExitCommand(self, self._relay_timeout)
        if self._mode == "unlocked_exit":
            # Уже разблокирован на выход, игнорируем
            return None
        self._mode = "exit_open"
        logger.info(f"[TurnstileDevice] mode={self._mode}, token={event.token}, user_id={event.user_id}")
        return OpenExitCommand(self, self._relay_timeout)

    def _on_access_denied(self, event: AccessDenied) -> Command:
        return DenyCommand(self, event.direction)

    def _on_device_command(self, event: DeviceCommand) -> Command | None:
        command = event.command

        if command == "open_entry":
            if self._mode == "unlocked_exit":
                self._mode = "idle"
                logger.info(f"[TurnstileDevice] mode={self._mode} (from unlocked_exit)")
                return CloseCommand(self)
            if self._mode == "unlocked_entry":
                # Переключение с разблокированного входа на разовый вход (без щелчка реле)
                self._mode = "entry_open"
                logger.info(f"[TurnstileDevice] mode={self._mode} (from unlocked_entry)")
                return OpenEntryCommand(self, self._button_timeout, skip_relay=True)
            if self._mode == "exit_open":
                # Переключение с разового выхода на разовый вход
                self._mode = "entry_open"
                logger.info(f"[TurnstileDevice] mode={self._mode} (from exit_open)")
                return OpenEntryCommand(self, self._button_timeout)
            if self._mode == "entry_open":
                # Уже открыто на один раз в ту же сторону, возвращаем ту же команду для обновления таймера
                return OpenEntryCommand(self, self._button_timeout)
            self._mode = "entry_open"
            logger.info(f"[TurnstileDevice] mode={self._mode} (from idle)")
            return OpenEntryCommand(self, self._button_timeout)

        if command == "open_exit":
            if self._mode == "unlocked_entry":
                self._mode = "idle"
                logger.info(f"[TurnstileDevice] mode={self._mode} (from unlocked_entry)")
                return CloseCommand(self)
            if self._mode == "unlocked_exit":
                # Переключение с разблокированного выхода на разовый выход (без щелчка реле)
                self._mode = "exit_open"
                logger.info(f"[TurnstileDevice] mode={self._mode} (from unlocked_exit)")
                return OpenExitCommand(self, self._button_timeout, skip_relay=True)
            if self._mode == "entry_open":
                # Переключение с разового входа на разовый выход
                self._mode = "exit_open"
                logger.info(f"[TurnstileDevice] mode={self._mode} (from entry_open)")
                return OpenExitCommand(self, self._button_timeout)
            if self._mode == "exit_open":
                # Уже открыто на один раз в ту же сторону, возвращаем ту же команду для обновления таймера
                return OpenExitCommand(self, self._button_timeout)
            self._mode = "exit_open"
            logger.info(f"[TurnstileDevice] mode={self._mode} (from idle)")
            return OpenExitCommand(self, self._button_timeout)

        if command == "unlock_entry":
            if self._mode == "entry_open":
                # Переключение с разового входа на разблокированный вход
                self._mode = "unlocked_entry"
                logger.info(f"[TurnstileDevice] mode={self._mode} (from entry_open)")
                return UnlockEntryCommand(self)
            if self._mode == "unlocked_exit":
                # Переключение с разблокированного выхода на разблокированный вход
                self._mode = "unlocked_entry"
                logger.info(f"[TurnstileDevice] mode={self._mode} (from unlocked_exit)")
                return UnlockEntryCommand(self)
            if self._mode == "unlocked_entry":
                # Уже разблокирован на вход, игнорируем
                return None
            if self._mode == "exit_open":
                # Переключение с разового выхода на разблокированный вход
                self._mode = "unlocked_entry"
                logger.info(f"[TurnstileDevice] mode={self._mode} (from exit_open)")
                return UnlockEntryCommand(self)
            self._mode = "unlocked_entry"
            logger.info(f"[TurnstileDevice] mode={self._mode} (from idle)")
            return UnlockEntryCommand(self)

        if command == "unlock_exit":
            if self._mode == "exit_open":
                # Переключение с разового выхода на разблокированный выход
                self._mode = "unlocked_exit"
                logger.info(f"[TurnstileDevice] mode={self._mode} (from exit_open)")
                return UnlockExitCommand(self)
            if self._mode == "unlocked_entry":
                # Переключение с разблокированного входа на разблокированный выход
                self._mode = "unlocked_exit"
                logger.info(f"[TurnstileDevice] mode={self._mode} (from unlocked_entry)")
                return UnlockExitCommand(self)
            if self._mode == "unlocked_exit":
                # Уже разблокирован на выход, игнорируем
                return None
            if self._mode == "entry_open":
                # Переключение с разового входа на разблокированный выход
                self._mode = "unlocked_exit"
                logger.info(f"[TurnstileDevice] mode={self._mode} (from entry_open)")
                return UnlockExitCommand(self)
            self._mode = "unlocked_exit"
            logger.info(f"[TurnstileDevice] mode={self._mode} (from idle)")
            return UnlockExitCommand(self)

        if command == "start_close_timer":
            return DelayedCloseCommand(self, self._button_timeout)

        if command == "close":
            if self._mode == "unlocked_entry":
                # Короткий Shift из разблокированного входа
                self._mode = "idle"
                logger.info(f"[TurnstileDevice] mode={self._mode} (from unlocked_entry)")
                return CloseCommand(self)
            if self._mode == "unlocked_exit":
                # Короткий Shift из разблокированного выхода
                self._mode = "idle"
                logger.info(f"[TurnstileDevice] mode={self._mode} (from unlocked_exit)")
                return CloseCommand(self)
            if self._mode == "entry_open":
                self._mode = "idle"
                logger.info(f"[TurnstileDevice] mode={self._mode} (from entry_open)")
                return CloseCommand(self)
            if self._mode == "exit_open":
                self._mode = "idle"
                logger.info(f"[TurnstileDevice] mode={self._mode} (from exit_open)")
                return CloseCommand(self)
            # Уже закрыт
            return None

        if command == "lock":
            if self._mode == "blocked":
                # Уже заблокирован, игнорируем
                return None
            if self._mode in ("entry_open", "exit_open", "alarm"):
                # Не блокируем, пока человек может проходить или активна тревога
                return None
            # idle / unlocked_entry / unlocked_exit
            old_mode = self._mode
            self.locked = True
            self._mode = "blocked"
            logger.info(f"[TurnstileDevice] mode={self._mode} (from {old_mode})")
            return LockCommand(self)

        if command == "unlock":
            self.locked = False
            self._mode = "idle"
            logger.info(f"[TurnstileDevice] mode={self._mode} (from blocked)")
            return UnlockCommand(self)

        if command == "cancel_unlock":
            self._mode = "idle"
            logger.info(f"[TurnstileDevice] mode={self._mode} (from unlocked)")
            return CloseCommand(self)

        return None

    def _on_alarm_changed(self, event: AlarmChanged) -> Command | None:
        if event.active:
            self._alarm = True
            old_mode = self._mode
            self._mode = "alarm"
            logger.info(f"[TurnstileDevice] mode={self._mode} (from {old_mode})")
            return AlarmCommand(self)
        self._alarm = False
        # Диаграмма: после отмены ОПС всегда возвращаемся в нормально закрыт.
        # Если установлен флаг админской блокировки, следующая проверка переведёт
        # устройство в blocked через handle().
        self._mode = "idle"
        logger.info(f"[TurnstileDevice] mode={self._mode} (from alarm)")
        return ClearAlarmCommand(self)

    def _on_passage_detected(self, event: PassageDetected) -> Command | None:
        # Закрываем только в режимах одноразового прохода
        if self._mode in ("entry_open", "exit_open"):
            old_mode = self._mode
            self._mode = "idle"
            logger.info(f"[TurnstileDevice] mode={self._mode} (from {old_mode}) - passage detected")
            return CloseCommand(self)
        # В unlocked режимах не закрываем - турникет должен оставаться открытым
        return None
