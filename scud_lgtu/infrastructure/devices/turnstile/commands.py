"""Команды устройства доступа (турникет/ворота/дверь).

Каждая команда — самодостаточная корутина: включает выходы, ждёт или ждёт
остановки, выключает выходы."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import List, Optional

from scud_lgtu.domain.models import OutputCommand

logger = logging.getLogger(__name__)



@dataclass(frozen=True)
class CommandMeta:
    """Метаданные команды для исполнителя."""
    name: str
    conflicts: tuple[str, ...] = ()
    state_label: Optional[str] = None
    end_state_label: Optional[str] = None


class Command:
    """Базовая команда устройства."""
    meta = CommandMeta("base")

    def __init__(self):
        self._stop = asyncio.Event()

    def request_stop(self) -> None:
        """Сигнал комаде завершить работу. Вызывается исполнителем."""
        self._stop.set()

    async def _sleep(self, timeout: float) -> bool:
        """Спать timeout секунд или до сигнала остановки.

        Возвращает True, если была запрошена остановка.
        """
        if timeout <= 0:
            return self._stop.is_set()
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False

    async def _wait_until_stopped(self) -> None:
        await self._stop.wait()

    async def run(self, executor: "CommandRunner") -> None:
        """Выполнить команду. Корутина завершается самостоятельно."""
        raise NotImplementedError

    def cleanup(self) -> List[OutputCommand]:
        """Запасной вариант выключения, если команду отменили насильно."""
        return []

    def refresh(self) -> None:
        """Обновить таймер команды без повторного выполнения."""
        pass


class _RelayCommand(Command):
    """Базовая команда с доступом к пинам устройства."""
    def __init__(self, device: "TurnstileDevice"):
        super().__init__()
        self._device = device


class OpenEntryCommand(_RelayCommand):
    """Разовое открытие на вход."""
    meta = CommandMeta(
        name="open_entry",
        conflicts=("open_exit", "unlock_entry", "unlock_exit"),
        state_label="entry_open",
        end_state_label="idle",
    )

    def __init__(self, device: "TurnstileDevice", duration: float, skip_cleanup: bool = False, skip_relay: bool = False):
        super().__init__(device)
        self._duration = duration
        self._refresh_requested = False
        self._skip_cleanup = skip_cleanup
        self._skip_relay = skip_relay

    async def run(self, executor) -> None:
        logger.info(f"OpenEntryCommand: открытие входа на {self._duration}с")
        try:
            if not self._skip_relay:
                await executor.apply([
                    OutputCommand(name=self._device.exit_relay, state=False),
                    OutputCommand(name=self._device.entry_relay, state=True),
                    OutputCommand(name=self._device.entry_green, state=True),
                    OutputCommand(name=self._device.entry_red, state=False),
                ])
            # Короткий бипер
            await executor.apply([OutputCommand(name=self._device.main_buzzer, state=True)])
            await self._sleep(0.2)
            await executor.apply([OutputCommand(name=self._device.main_buzzer, state=False)])
            # Основной таймер с возможностью обновления
            while True:
                if await self._sleep(self._duration - 0.2):
                    break  # Запрошена остановка
                if self._refresh_requested:
                    self._refresh_requested = False
                    continue  # Продолжаем ждать
                break  # Таймер истёк
        finally:
            self._device.current_token = None
            self._device.current_user_id = None
            if not self._skip_cleanup:
                await executor.apply([
                    OutputCommand(name=self._device.entry_relay, state=False),
                    OutputCommand(name=self._device.entry_green, state=False),
                ])

    def refresh(self) -> None:
        """Обновить таймер без повторного выполнения."""
        self._refresh_requested = True

    def cleanup(self) -> List[OutputCommand]:
        self._device.current_token = None
        self._device.current_user_id = None
        return [
            OutputCommand(name=self._device.entry_relay, state=False),
            OutputCommand(name=self._device.entry_green, state=False),
            OutputCommand(name=self._device.main_buzzer, state=False),
        ]


class OpenExitCommand(_RelayCommand):
    """Разовое открытие на выход."""
    meta = CommandMeta(
        name="open_exit",
        conflicts=("open_entry", "unlock_exit", "unlock_entry"),
        state_label="exit_open",
        end_state_label="idle",
    )

    def __init__(self, device: "TurnstileDevice", duration: float, skip_cleanup: bool = False, skip_relay: bool = False):
        super().__init__(device)
        self._duration = duration
        self._refresh_requested = False
        self._skip_cleanup = skip_cleanup
        self._skip_relay = skip_relay

    async def run(self, executor) -> None:
        logger.info(f"OpenExitCommand: открытие выхода на {self._duration}с")
        try:
            if not self._skip_relay:
                await executor.apply([
                    OutputCommand(name=self._device.entry_relay, state=False),
                    OutputCommand(name=self._device.exit_relay, state=True),
                    OutputCommand(name=self._device.exit_green, state=True),
                    OutputCommand(name=self._device.exit_red, state=False),
                ])
            # Короткий бипер
            await executor.apply([OutputCommand(name=self._device.main_buzzer, state=True)])
            await self._sleep(0.2)
            await executor.apply([OutputCommand(name=self._device.main_buzzer, state=False)])
            # Основной таймер с возможностью обновления
            while True:
                if await self._sleep(self._duration - 0.2):
                    break  # Запрошена остановка
                if self._refresh_requested:
                    self._refresh_requested = False
                    continue  # Продолжаем ждать
                break  # Таймер истёк
        finally:
            self._device.current_token = None
            self._device.current_user_id = None
            if not self._skip_cleanup:
                await executor.apply([
                    OutputCommand(name=self._device.exit_relay, state=False),
                    OutputCommand(name=self._device.exit_green, state=False),
                ])

    def refresh(self) -> None:
        """Обновить таймер без повторного выполнения."""
        self._refresh_requested = True

    def cleanup(self) -> List[OutputCommand]:
        self._device.current_token = None
        self._device.current_user_id = None
        return [
            OutputCommand(name=self._device.exit_relay, state=False),
            OutputCommand(name=self._device.exit_green, state=False),
            OutputCommand(name=self._device.main_buzzer, state=False),
        ]


class UnlockEntryCommand(_RelayCommand):
    """Постоянно открытый вход."""
    meta = CommandMeta(
        name="unlock_entry",
        conflicts=("open_entry", "open_exit", "unlock_exit"),
        state_label="unlocked_entry",
        end_state_label="idle",
    )

    def __init__(self, device: "TurnstileDevice"):
        super().__init__(device)

    async def run(self, executor) -> None:
        logger.info("UnlockEntryCommand: разблокирован вход")
        await executor.apply([
            OutputCommand(name=self._device.exit_relay, state=False),
            OutputCommand(name=self._device.entry_relay, state=True),
            OutputCommand(name=self._device.entry_green, state=True),
            OutputCommand(name=self._device.entry_red, state=False),
        ])
        # Короткий бипер
        await executor.apply([OutputCommand(name=self._device.main_buzzer, state=True)])
        await self._sleep(0.2)
        await executor.apply([OutputCommand(name=self._device.main_buzzer, state=False)])
        # Реле остаётся открытым, пока не будет явной команды закрытия

    def cleanup(self) -> List[OutputCommand]:
        return [
            OutputCommand(name=self._device.entry_relay, state=False),
            OutputCommand(name=self._device.entry_green, state=False),
            OutputCommand(name=self._device.main_buzzer, state=False),
        ]


class UnlockExitCommand(_RelayCommand):
    """Постоянно открытый выход."""
    meta = CommandMeta(
        name="unlock_exit",
        conflicts=("open_entry", "open_exit", "unlock_entry"),
        state_label="unlocked_exit",
        end_state_label="idle",
    )

    def __init__(self, device: "TurnstileDevice"):
        super().__init__(device)

    async def run(self, executor) -> None:
        logger.info("UnlockExitCommand: разблокирован выход")
        await executor.apply([
            OutputCommand(name=self._device.entry_relay, state=False),
            OutputCommand(name=self._device.exit_relay, state=True),
            OutputCommand(name=self._device.exit_green, state=True),
            OutputCommand(name=self._device.exit_red, state=False),
        ])
        # Короткий бипер
        await executor.apply([OutputCommand(name=self._device.main_buzzer, state=True)])
        await self._sleep(0.2)
        await executor.apply([OutputCommand(name=self._device.main_buzzer, state=False)])
        # Реле остаётся открытым, пока не будет явной команды закрытия

    def cleanup(self) -> List[OutputCommand]:
        return [
            OutputCommand(name=self._device.exit_relay, state=False),
            OutputCommand(name=self._device.exit_green, state=False),
            OutputCommand(name=self._device.main_buzzer, state=False),
        ]


class CloseCommand(_RelayCommand):
    """Закрыть устройство."""
    meta = CommandMeta(
        name="close",
        conflicts=("open_entry", "open_exit", "unlock_entry", "unlock_exit"),
        state_label="idle",
    )

    async def run(self, executor) -> None:
        logger.info("CloseCommand: закрытие")
        self._device.current_token = None
        self._device.current_user_id = None
        await executor.apply([
            OutputCommand(name=self._device.entry_relay, state=False),
            OutputCommand(name=self._device.exit_relay, state=False),
            OutputCommand(name=self._device.entry_green, state=False),
            OutputCommand(name=self._device.exit_green, state=False),
            OutputCommand(name=self._device.main_buzzer, state=False),
        ])

    def cleanup(self) -> List[OutputCommand]:
        return [
            OutputCommand(name=self._device.entry_relay, state=False),
            OutputCommand(name=self._device.exit_relay, state=False),
            OutputCommand(name=self._device.entry_green, state=False),
            OutputCommand(name=self._device.exit_green, state=False),
            OutputCommand(name=self._device.main_buzzer, state=False),
        ]


class DelayedCloseCommand(_RelayCommand):
    """Закрыть через указанное время."""
    meta = CommandMeta(
        name="delayed_close",
        conflicts=("open_exit",),
        state_label="idle",
    )

    def __init__(self, device: "TurnstileDevice", delay: float):
        super().__init__(device)
        self._delay = delay

    async def run(self, executor) -> None:
        logger.info(f"DelayedCloseCommand: задержка закрытия {self._delay}с")
        if not await self._sleep(self._delay):
            await CloseCommand(self._device).run(executor)


class LockCommand(_RelayCommand):
    """Заблокировать устройство."""
    meta = CommandMeta(
        name="lock",
        conflicts=("open_entry", "open_exit", "unlock_entry", "unlock_exit", "close"),
        state_label="blocked",
        end_state_label="idle",
    )

    async def run(self, executor) -> None:
        logger.info("LockCommand: блокировка")
        try:
            self._device.locked = True
            self._device.current_token = None
            self._device.current_user_id = None
            await executor.apply([
                OutputCommand(name=self._device.entry_relay, state=False),
                OutputCommand(name=self._device.exit_relay, state=False),
                OutputCommand(name=self._device.entry_green, state=False),
                OutputCommand(name=self._device.exit_green, state=False),
                OutputCommand(name=self._device.entry_red, state=True),
                OutputCommand(name=self._device.exit_red, state=True),
                OutputCommand(name=self._device.main_buzzer, state=False),
            ])
            await self._wait_until_stopped()
        finally:
            await executor.apply([
                OutputCommand(name=self._device.entry_red, state=False),
                OutputCommand(name=self._device.exit_red, state=False),
            ])

    def cleanup(self) -> List[OutputCommand]:
        return [
            OutputCommand(name=self._device.entry_red, state=False),
            OutputCommand(name=self._device.exit_red, state=False),
        ]


class UnlockCommand(_RelayCommand):
    """Разблокировать устройство."""
    meta = CommandMeta(
        name="unlock",
        conflicts=("lock",),
        state_label="idle",
    )

    async def run(self, executor) -> None:
        logger.info("UnlockCommand: разблокировка")
        self._device.locked = False
        await executor.apply([
            OutputCommand(name=self._device.entry_red, state=False),
            OutputCommand(name=self._device.exit_red, state=False),
        ])


class AlarmCommand(_RelayCommand):
    """Режим тревоги."""
    meta = CommandMeta(
        name="alarm",
        conflicts=("open_entry", "open_exit", "unlock_entry", "unlock_exit", "close", "lock", "unlock"),
        state_label="alarm",
        end_state_label="idle",
    )

    def __init__(self, device: "TurnstileDevice"):
        super().__init__(device)
        self._on_duration = device.alarm_beep_on_duration
        self._off_duration = device.alarm_beep_off_duration

    async def run(self, executor) -> None:
        logger.info("AlarmCommand: тревога")
        self._device.current_token = None
        self._device.current_user_id = None
        try:
            await executor.apply([
                OutputCommand(name=self._device.entry_relay, state=False),
                OutputCommand(name=self._device.exit_relay, state=True),  # эвакуация
                OutputCommand(name=self._device.entry_green, state=False),
                OutputCommand(name=self._device.exit_green, state=False),
                OutputCommand(name=self._device.entry_red, state=False),
                OutputCommand(name=self._device.exit_red, state=True),
                OutputCommand(name=self._device.main_buzzer, state=True),
            ])
            while True:
                if await self._sleep(self._on_duration):
                    break
                await executor.apply([OutputCommand(name=self._device.main_buzzer, state=False)])
                if await self._sleep(self._off_duration):
                    break
                await executor.apply([OutputCommand(name=self._device.main_buzzer, state=True)])
        finally:
            await executor.apply([
                OutputCommand(name=self._device.entry_relay, state=False),
                OutputCommand(name=self._device.exit_relay, state=False),
                OutputCommand(name=self._device.entry_red, state=False),
                OutputCommand(name=self._device.exit_red, state=False),
                OutputCommand(name=self._device.main_buzzer, state=False),
            ])

    def cleanup(self) -> List[OutputCommand]:
        return [
            OutputCommand(name=self._device.entry_relay, state=False),
            OutputCommand(name=self._device.exit_relay, state=False),
            OutputCommand(name=self._device.entry_red, state=False),
            OutputCommand(name=self._device.exit_red, state=False),
            OutputCommand(name=self._device.main_buzzer, state=False),
        ]


class ClearAlarmCommand(_RelayCommand):
    """Сброс режима тревоги."""

    def __init__(self, device: "TurnstileDevice"):
        super().__init__(device)
        end_label = "blocked" if device.locked else "idle"
        self.meta = CommandMeta(
            name="clear_alarm",
            conflicts=("alarm",),
            state_label=end_label,
        )

    async def run(self, executor) -> None:
        logger.info("ClearAlarmCommand: сброс тревоги")
        commands = [
            OutputCommand(name=self._device.entry_relay, state=False),
            OutputCommand(name=self._device.exit_relay, state=False),
            OutputCommand(name=self._device.entry_green, state=False),
            OutputCommand(name=self._device.exit_green, state=False),
            OutputCommand(name=self._device.main_buzzer, state=False),
        ]
        if self._device.locked:
            commands.extend([
                OutputCommand(name=self._device.entry_red, state=True),
                OutputCommand(name=self._device.exit_red, state=True),
            ])
        else:
            commands.extend([
                OutputCommand(name=self._device.entry_red, state=False),
                OutputCommand(name=self._device.exit_red, state=False),
            ])
        await executor.apply(commands)
        # Чисто событийно: после сброса тревоги сразу формализуем
        # админскую блокировку, если она установлена.
        if self._device.locked:
            self._device._mode = "blocked"


class DenyCommand(_RelayCommand):
    """Отказ в доступе: бипер + красный индикатор."""
    meta = CommandMeta(
        name="deny",
        conflicts=("deny",),
    )

    def __init__(self, device: "TurnstileDevice", direction: str):
        super().__init__(device)
        self._direction = direction

    async def run(self, executor) -> None:
        logger.info(f"DenyCommand: отказ, direction={self._direction}")
        red = self._device.entry_red if self._direction == "entry" else self._device.exit_red
        green = self._device.entry_green if self._direction == "entry" else self._device.exit_green
        count = self._device.deny_beep_count
        duration = self._device.deny_beep_duration
        pause = self._device.deny_beep_pause

        try:
            await executor.apply([OutputCommand(name=green, state=False)])
            for i in range(count):
                if self._stop.is_set():
                    break
                await executor.apply([
                    OutputCommand(name=self._device.main_buzzer, state=True),
                    OutputCommand(name=red, state=True),
                ])
                if await self._sleep(duration):
                    break
                await executor.apply([
                    OutputCommand(name=self._device.main_buzzer, state=False),
                    OutputCommand(name=red, state=False),
                ])
                if i < count - 1 and await self._sleep(pause):
                    break
        finally:
            await executor.apply([
                OutputCommand(name=self._device.main_buzzer, state=False),
                OutputCommand(name=red, state=False),
            ])

    def cleanup(self) -> List[OutputCommand]:
        red = self._device.entry_red if self._direction == "entry" else self._device.exit_red
        return [
            OutputCommand(name=self._device.main_buzzer, state=False),
            OutputCommand(name=red, state=False),
        ]


