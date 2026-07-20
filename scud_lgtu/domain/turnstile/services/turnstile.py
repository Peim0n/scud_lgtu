"""
Конечный автомат турникета системы СКУД.

Этот модуль реализует конечный автомат для управления турникетом с состояниями:
- IDLE: турникет закрыт
- ENTRY_OPEN: турникет открыт для входа
- EXIT_OPEN: турникет открыт для выхода
- ALARM: режим тревоги (пожарная тревога)
- BLOCKED: турникет заблокирован

Классы
-------
- TurnstileStateEnum: перечисление состояний турникета
- TurnstileState: конечный автомат турникета с методами управления и асинхронными операциями

Методы TurnstileState
----------------------
- can_open: проверить, можно ли открыть турникет в заданном направлении
- open_entry: открыть турникет для входа
- open_exit: открыть турникет для выхода
- close: закрыть турникет
- start_open_timer: запустить таймер закрытия
- deny_beep_sequence: асинхронная задача для выполнения 3 коротких писков при отказе
- open_entry_async: асинхронное открытие турникета для входа с автоматическим закрытием
- set_indicator_async: асинхронная задача для включения индикатора на заданное время
- close_async: асинхронное закрытие турникета
- set_alarm: установить режим тревоги
- clear_alarm: сбросить режим тревоги
- block: заблокировать турникет
- unblock: разблокировать турникет
- tick: периодический тик для обработки таймаутов
"""
from enum import Enum
from dataclasses import dataclass
from typing import List, Optional
from time import time
from scud_lgtu.domain.common.models.models import OutputCommand
from scud_lgtu.domain.common.enums.enums import DirectionEnum
from scud_lgtu.domain.access.ports.ports import ConfigResolver
import logging
import asyncio

logger = logging.getLogger(__name__)


class TurnstileStateEnum(str, Enum):
    """Состояния турникета."""
    IDLE = "idle"
    ENTRY_OPEN = "entry_open"
    EXIT_OPEN = "exit_open"
    ALARM = "alarm"
    BLOCKED = "blocked"


@dataclass
class TurnstileState:
    """Конечный автомат турникета."""

    def __init__(self, auth_timeout: float = 5.0, timings: dict = None, devices: dict = None, resolver: Optional[ConfigResolver] = None):
        """
        Инициализировать состояние турникета.

        Parameters
        ----------
        auth_timeout : float
            Время действия авторизации в секундах (по умолчанию 5.0)
        timings : dict, optional
            Словарь таймингов из конфигурации. Если None, используются дефолтные значения.
        devices : dict, optional
            Словарь конфигурации устройств из config.yml. Содержит мапинг реле, индикаторов и биперов.
            Для обратной совместимости со старой архитектурой.
        resolver : ConfigResolver, optional
            Резолвер конфигурационных имен для новой архитектуры.
        """
        self._current_state = TurnstileStateEnum.IDLE
        self._open_since: Optional[float] = None
        self._alarm_since: Optional[float] = None
        self._auth_timeout = auth_timeout
        self._output_commands: List[OutputCommand] = []
        self._beep_since: Optional[float] = None
        self._resolver = resolver

        # Загрузка конфигурации
        if resolver:
            # Новая архитектура с ConfigResolver
            self._load_from_resolver(timings)
        else:
            # Старая архитектура для обратной совместимости
            self._load_from_legacy(timings, devices)

        self._alarm_beep_since: Optional[float] = None
        self._alarm_beep_on = False
        self._open_task: Optional[asyncio.Task] = None  # Активная задача открытия
        self._deny_beep_task: Optional[asyncio.Task] = None  # Активная задача deny beep
        self._indicator_task: Optional[asyncio.Task] = None  # Активная задача индикатора

    def _load_from_resolver(self, timings: dict = None) -> None:
        """Загрузить конфигурацию из ConfigResolver."""
        if not self._resolver:
            return

        if timings is None:
            timings = {}

        # Загрузка таймингов из секции business через интерфейс ConfigResolver
        self._beep_duration = self._resolver.get_timing("business", "beep_signal_duration_s", timings.get("beep_signal_duration_s", 0.1))
        alarm_on = self._resolver.get_timing("business", "alarm_beep_on_duration_s", timings.get("alarm_beep_on_duration_s", 0.5))
        alarm_off = self._resolver.get_timing("business", "alarm_beep_off_duration_s", timings.get("alarm_beep_off_duration_s", 0.5))
        self._alarm_beep_cycle = alarm_on + alarm_off
        self._deny_beep_duration = self._resolver.get_timing("business", "deny_beep_duration_s", timings.get("deny_beep_duration_s", 0.1))
        self._deny_beep_pause = self._resolver.get_timing("business", "deny_beep_pause_s", timings.get("deny_beep_pause_s", 0.1))
        self._deny_beep_total = self._resolver.get_timing("business", "deny_beep_count", timings.get("deny_beep_count", 3))
        self._open_beep_duration = self._resolver.get_timing("business", "open_beep_duration_s", timings.get("open_beep_duration_s", 0.1))
        self._indicator_duration = self._resolver.get_timing("business", "indicator_duration_s", timings.get("indicator_duration_s", 2.0))

        # Загрузка бизнес-имен (без резолвинга - это ответственность Infrastructure слоя)
        self._entry_relay = "entry_relay"
        self._exit_relay = "exit_relay"
        self._main_buzzer = "main_buzzer"
        self._entry_green = "inner_indicator_success"
        self._entry_red = "inner_indicator_fail"
        self._exit_green = "outer_indicator_success"
        self._exit_red = "outer_indicator_fail"

        logger.info("[TurnstileState] Конфигурация загружена через ConfigResolver")

    def _load_from_legacy(self, timings: dict = None, devices: dict = None) -> None:
        """Загрузить конфигурацию из старого формата (для обратной совместимости)."""
        if timings is None:
            timings = {}
        if devices is None:
            devices = {}

        self._beep_duration = timings.get("beep_signal_duration_s", 0.1)
        self._alarm_beep_cycle = timings.get("alarm_beep_on_duration_s", 0.5) + timings.get("alarm_beep_off_duration_s", 0.5)
        self._deny_beep_duration = timings.get("deny_beep_duration_s", 0.1)
        self._deny_beep_pause = timings.get("deny_beep_pause_s", 0.1)
        self._deny_beep_total = timings.get("deny_beep_count", 3)
        self._open_beep_duration = timings.get("open_beep_duration_s", 0.1)
        self._indicator_duration = timings.get("indicator_duration_s", 2.0)

        relays = devices.get("relays", {})
        buzzers = devices.get("buzzers", {})

        self._entry_relay = relays.get("entry_relay", {}).get("label", "rel1")
        self._exit_relay = relays.get("exit_relay", {}).get("label", "rel2")
        self._main_buzzer = buzzers.get("main_buzzer", {}).get("label", "buz")

        # Для индикаторов используем дефолтные имена
        self._entry_green = "w1_green"
        self._entry_red = "w1_red"
        self._exit_green = "w2_green"
        self._exit_red = "w2_red"

        logger.info("[TurnstileState] Конфигурация загружена из legacy формата")
    
    def can_open(self, direction: DirectionEnum) -> bool:
        """Проверить, можно ли открыть турникет в заданном направлении."""
        if self._current_state == TurnstileStateEnum.ALARM:
            return True  # Режим тревоги разрешает любое направление
        if self._current_state == TurnstileStateEnum.BLOCKED:
            return False
        if self._current_state == TurnstileStateEnum.IDLE:
            return True
        if self._current_state == TurnstileStateEnum.ENTRY_OPEN and direction == DirectionEnum.IN:
            return True
        if self._current_state == TurnstileStateEnum.EXIT_OPEN and direction == DirectionEnum.OUT:
            return True
        return False
    
    def open_entry(self, start_timer: bool = False) -> List[OutputCommand]:
        """Открыть турникет для входа.

        Args:
            start_timer: Если True, запустить таймер закрытия сразу (для карт).
                        Если False, таймер запускается отдельно (для кнопок).
        """
        if not self.can_open(DirectionEnum.IN):
            return []

        self._current_state = TurnstileStateEnum.ENTRY_OPEN
        if start_timer:
            self._open_since = time()
        else:
            self._open_since = None  # Таймер запускается отдельно при отжатии кнопки
        self._beep_since = time()  # Start beep timer
        self._output_commands = [
            OutputCommand(name=self._entry_relay, state=True),
            OutputCommand(name=self._entry_green, state=True),
            OutputCommand(name=self._entry_red, state=False),
            OutputCommand(name=self._main_buzzer, state=True),
        ]
        return self._output_commands
    
    def open_exit(self, start_timer: bool = False) -> List[OutputCommand]:
        """Открыть турникет для выхода.

        Args:
            start_timer: Если True, запустить таймер закрытия сразу (для карт).
                        Если False, таймер запускается отдельно (для кнопок).
        """
        if not self.can_open(DirectionEnum.OUT):
            return []

        # В режиме тревоги не меняем состояние, просто открываем реле
        if self._current_state != TurnstileStateEnum.ALARM:
            self._current_state = TurnstileStateEnum.EXIT_OPEN

        if start_timer:
            self._open_since = time()
        else:
            self._open_since = None  # Таймер запускается отдельно при отжатии кнопки
        self._beep_since = time()  # Start beep timer
        self._output_commands = [
            OutputCommand(name=self._exit_relay, state=True),
            OutputCommand(name=self._exit_green, state=True),
            OutputCommand(name=self._exit_red, state=False),
            OutputCommand(name=self._main_buzzer, state=True),
        ]
        return self._output_commands
    
    def close(self) -> List[OutputCommand]:
        """Закрыть турникет."""
        if self._current_state == TurnstileStateEnum.IDLE:
            return []

        self._current_state = TurnstileStateEnum.IDLE
        self._open_since = None
        self._output_commands = [
            OutputCommand(name=self._entry_relay, state=False),
            OutputCommand(name=self._exit_relay, state=False),
            OutputCommand(name=self._entry_green, state=False),
            OutputCommand(name=self._exit_green, state=False),
        ]
        return self._output_commands
    
    def start_open_timer(self) -> None:
        """Запустить таймер закрытия (при отжатии кнопки)."""
        if self._current_state in (TurnstileStateEnum.ENTRY_OPEN, TurnstileStateEnum.EXIT_OPEN):
            self._open_since = time()
    
    async def deny_beep_sequence(self, event_bus) -> None:
        """Асинхронная задача для выполнения 3 коротких писков."""
        from scud_lgtu.domain.common.events.events import OutputCommandsGenerated
        
        # Игнорировать новую задачу если предыдущая еще выполняется
        if self._deny_beep_task and not self._deny_beep_task.done():
            logger.debug("deny_beep: ignored - previous task still running")
            return
        
        self._deny_beep_task = asyncio.current_task()
        
        try:
            for i in range(self._deny_beep_total):
                # Включить бипер
                commands = [OutputCommand(name=self._main_buzzer, state=True)]
                event_bus.publish(OutputCommandsGenerated(commands=commands))
                logger.debug(f"deny_beep: beep {i+1} ON")

                # Подождать configured duration
                await asyncio.sleep(self._deny_beep_duration)

                # Выключить бипер
                commands = [OutputCommand(name=self._main_buzzer, state=False)]
                event_bus.publish(OutputCommandsGenerated(commands=commands))
                logger.debug(f"deny_beep: beep {i+1} OFF")
                
                # Подождать configured pause перед следующим писком
                if i < self._deny_beep_total - 1:  # Не ждать после последнего писка
                    await asyncio.sleep(self._deny_beep_pause)
            
            logger.debug("deny_beep: sequence completed")
        except asyncio.CancelledError:
            logger.debug("deny_beep: task cancelled")
        finally:
            self._deny_beep_task = None
    
    async def _open_async_common(self, event_bus, direction: DirectionEnum, start_timer: bool = True) -> None:
        """Общая логика асинхронного открытия турникета."""
        from scud_lgtu.domain.common.events.events import OutputCommandsGenerated

        if not self.can_open(direction):
            return

        # Игнорировать новую задачу если предыдущая еще выполняется
        if self._open_task and not self._open_task.done():
            logger.debug(f"open_{direction.value}: ignored - previous task still running")
            return

        self._open_task = asyncio.current_task()

        try:
            # Определяем пины в зависимости от направления
            if direction == DirectionEnum.IN:
                self._current_state = TurnstileStateEnum.ENTRY_OPEN
                relay = self._entry_relay
                green = self._entry_green
                red = self._entry_red
            else:
                self._current_state = TurnstileStateEnum.EXIT_OPEN
                relay = self._exit_relay
                green = self._exit_green
                red = self._exit_red

            # Открыть реле, включить зеленый, выключить красный, включить бипер
            commands = [
                OutputCommand(name=relay, state=True),
                OutputCommand(name=green, state=True),
                OutputCommand(name=red, state=False),
                OutputCommand(name=self._main_buzzer, state=True),
            ]
            event_bus.publish(OutputCommandsGenerated(commands=commands))
            logger.debug(f"open_{direction.value}: opened")

            # Выключить бипер через configured duration
            await asyncio.sleep(self._open_beep_duration)
            commands = [OutputCommand(name=self._main_buzzer, state=False)]
            event_bus.publish(OutputCommandsGenerated(commands=commands))
            logger.debug(f"open_{direction.value}: beep off")

            # Запустить таймер закрытия если нужно
            if start_timer:
                self.start_open_timer()

        except asyncio.CancelledError:
            logger.debug(f"open_{direction.value}: task cancelled")
        finally:
            self._open_task = None

    async def open_entry_async(self, event_bus, start_timer: bool = True) -> None:
        """Асинхронное открытие турникета для входа с автоматическим закрытием."""
        await self._open_async_common(event_bus, DirectionEnum.IN, start_timer)

    async def open_exit_async(self, event_bus, start_timer: bool = True) -> None:
        """Асинхронное открытие турникета для выхода с автоматическим закрытием."""
        await self._open_async_common(event_bus, DirectionEnum.OUT, start_timer)

    async def set_indicator_async(self, event_bus, name: str, state: bool, duration: float = None) -> None:
        """Асинхронная задача для включения индикатора на заданное время."""
        from scud_lgtu.domain.common.events.events import OutputCommandsGenerated
        
        # Игнорировать новую задачу если предыдущая еще выполняется
        if self._indicator_task and not self._indicator_task.done():
            logger.debug(f"set_indicator: ignored - previous task still running")
            return
        
        self._indicator_task = asyncio.current_task()
        
        try:
            # Включить индикатор
            commands = [OutputCommand(name=name, state=state)]
            event_bus.publish(OutputCommandsGenerated(commands=commands))
            logger.debug(f"set_indicator: {name}={state}")
            
            # Если задана длительность - выключить через это время
            if duration is not None:
                await asyncio.sleep(duration)
                commands = [OutputCommand(name=name, state=False)]
                event_bus.publish(OutputCommandsGenerated(commands=commands))
                logger.debug(f"set_indicator: {name}=False after {duration}s")
        except asyncio.CancelledError:
            logger.debug("set_indicator: task cancelled")
        finally:
            self._indicator_task = None
    
    async def close_async(self, event_bus) -> None:
        """Асинхронное закрытие турникета."""
        from scud_lgtu.domain.common.events.events import OutputCommandsGenerated
        
        # Закрыть реле, выключить индикаторы
        commands = [
            OutputCommand(name="rel1", state=False),
            OutputCommand(name="w1_green", state=False),
            OutputCommand(name="w1_red", state=False),
        ]
        event_bus.publish(OutputCommandsGenerated(commands=commands))
        
        self._current_state = TurnstileStateEnum.IDLE
        self._open_since = None
        logger.debug("close_async: turnstile closed")
    
    async def _close_after_timeout(self, event_bus, timeout: float) -> None:
        """Асинхронная задача для закрытия через таймаут."""
        from scud_lgtu.domain.common.events.events import OutputCommandsGenerated
        
        await asyncio.sleep(timeout)
        
        # Закрыть только если всё еще открыто
        if self._current_state in (TurnstileStateEnum.ENTRY_OPEN, TurnstileStateEnum.EXIT_OPEN):
            commands = [
                OutputCommand(name="rel1", state=False),
                OutputCommand(name="rel2", state=False),
                OutputCommand(name="w1_green", state=False),
                OutputCommand(name="w2_green", state=False),
            ]
            event_bus.publish(OutputCommandsGenerated(commands=commands))
            self._current_state = TurnstileStateEnum.IDLE
            logger.debug(f"close_after_timeout: closed turnstile")
    
    def set_alarm(self) -> List[OutputCommand]:
        """Установить режим тревоги (пожарная тревога)."""
        if self._current_state == TurnstileStateEnum.ALARM:
            return []

        self._current_state = TurnstileStateEnum.ALARM
        self._alarm_since = time()
        self._alarm_beep_since = time()
        self._alarm_beep_on = True
        self._output_commands = [
            OutputCommand(name=self._exit_relay, state=True),  # Только выходное реле
            OutputCommand(name=self._exit_red, state=True),     # Красный индикатор на выходе
            OutputCommand(name=self._main_buzzer, state=True),
        ]
        return self._output_commands
    
    def clear_alarm(self) -> List[OutputCommand]:
        """Сбросить режим тревоги."""
        if self._current_state != TurnstileStateEnum.ALARM:
            return []

        self._current_state = TurnstileStateEnum.IDLE
        self._alarm_since = None
        self._alarm_beep_since = None
        self._alarm_beep_on = False
        self._output_commands = [
            OutputCommand(name=self._exit_relay, state=False),  # Только выходное реле
            OutputCommand(name=self._exit_red, state=False),     # Красный индикатор на выходе
            OutputCommand(name=self._main_buzzer, state=False),
        ]
        return self._output_commands
    
    def block(self) -> List[OutputCommand]:
        """Заблокировать турникет."""
        if self._current_state == TurnstileStateEnum.BLOCKED:
            return []

        self._current_state = TurnstileStateEnum.BLOCKED
        self._output_commands = [
            OutputCommand(name=self._entry_relay, state=False),
            OutputCommand(name=self._exit_relay, state=False),
            OutputCommand(name=self._entry_red, state=True),
            OutputCommand(name=self._exit_red, state=True),
        ]
        return self._output_commands
    
    def unblock(self) -> List[OutputCommand]:
        """Разблокировать турникет."""
        if self._current_state != TurnstileStateEnum.BLOCKED:
            return []

        self._current_state = TurnstileStateEnum.IDLE
        self._output_commands = [
            OutputCommand(name=self._entry_red, state=False),
            OutputCommand(name=self._exit_red, state=False),
        ]
        return self._output_commands
    
    def tick(self, now: float) -> List[OutputCommand]:
        """Периодический тик для обработки таймаутов."""
        commands: List[OutputCommand] = []
        
        # Автоматическое закрытие после таймаута
        if self._open_since and (now - self._open_since) > self._auth_timeout:
            commands.extend(self.close())
        
        # Автоматическое выключение бипера после длительности
        if self._beep_since and (now - self._beep_since) > self._beep_duration:
            commands.append(OutputCommand(name=self._main_buzzer, state=False))
            self._beep_since = None
        
        # Периодический бипер при тревоге (0.5 сек on, 0.5 сек off)
        if self._current_state == TurnstileStateEnum.ALARM and self._alarm_beep_since:
            elapsed = now - self._alarm_beep_since
            if elapsed > self._alarm_beep_cycle:
                # Переключить состояние бипера
                self._alarm_beep_on = not self._alarm_beep_on
                self._alarm_beep_since = now
                commands.append(OutputCommand(name=self._main_buzzer, state=self._alarm_beep_on))
        
        
        return commands
    
    @property
    def current_state(self) -> TurnstileStateEnum:
        """Получить текущее состояние."""
        return self._current_state
    
    @property
    def is_alarm_active(self) -> bool:
        """Проверить, активна ли тревога."""
        return self._current_state == TurnstileStateEnum.ALARM
