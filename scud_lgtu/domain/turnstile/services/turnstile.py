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

    def __init__(self, auth_timeout: float, timings: dict, resolver: ConfigResolver):
        """
        Инициализировать состояние турникета.

        Parameters
        ----------
        auth_timeout : float
            Время действия авторизации в секундах.
        timings : dict
            Словарь таймингов из конфигурации.
        resolver : ConfigResolver
            Резолвер конфигурационных имен.
        """

        self._current_state = TurnstileStateEnum.IDLE
        self._open_since: Optional[float] = None
        self._open_timeout: float = auth_timeout
        self._alarm_since: Optional[float] = None
        self._auth_timeout = auth_timeout
        self._output_commands: List[OutputCommand] = []
        self._beep_since: Optional[float] = None
        self._resolver = resolver
        self._hold_until: Optional[float] = None  # удержание открытым по датчикам
        self._current_token: Optional[str] = None
        self._current_user_id: Optional[int] = None

        self._load_from_resolver(timings)

        self._alarm_beep_since: Optional[float] = None
        self._alarm_beep_on = False
        self._open_task: Optional[asyncio.Task] = None  # Активная задача открытия
        self._deny_beep_task: Optional[asyncio.Task] = None  # Активная задача deny beep
        self._indicator_task: Optional[asyncio.Task] = None  # Активная задача индикатора

    def _load_from_resolver(self, timings: dict) -> None:
        """Загрузить конфигурацию из ConfigResolver."""
        if not self._resolver:
            return

        # Загрузка таймингов из секции business через интерфейс ConfigResolver
        self._beep_duration = self._resolver.get_timing("business", "beep_signal_duration_s", timings["beep_signal_duration_s"])
        alarm_on = self._resolver.get_timing("business", "alarm_beep_on_duration_s", timings["alarm_beep_on_duration_s"])
        alarm_off = self._resolver.get_timing("business", "alarm_beep_off_duration_s", timings["alarm_beep_off_duration_s"])
        self._alarm_beep_cycle = alarm_on + alarm_off
        self._deny_beep_duration = self._resolver.get_timing("business", "deny_beep_duration_s", timings["deny_beep_duration_s"])
        self._deny_beep_pause = self._resolver.get_timing("business", "deny_beep_pause_s", timings["deny_beep_pause_s"])
        self._deny_beep_total = self._resolver.get_timing("business", "deny_beep_count", timings["deny_beep_count"])
        self._open_beep_duration = self._resolver.get_timing("business", "open_beep_duration_s", timings["open_beep_duration_s"])
        self._indicator_duration = self._resolver.get_timing("business", "indicator_duration_s", timings["indicator_duration_s"])

        # Отдельные таймауты закрытия: кнопка (после отжатия) и карта/QR (после открытия)
        self._button_timeout = self._resolver.get_timing("business", "button_timer_duration_s", timings["button_timer_duration_s"])
        self._relay_timeout = self._resolver.get_timing("business", "relay_open_duration_s", timings["relay_open_duration_s"])

        # Загрузка бизнес-имен (без резолвинга - это ответственность Infrastructure слоя)
        self._entry_relay = "entry_relay"
        self._exit_relay = "exit_relay"
        self._main_buzzer = "main_buzzer"
        self._entry_green = "inner_indicator_success"
        self._entry_red = "inner_indicator_fail"
        self._exit_green = "outer_indicator_success"
        self._exit_red = "outer_indicator_fail"

        logger.info("[TurnstileState] Конфигурация загружена через ConfigResolver")

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
        self._hold_until = None  # сбросить удержание от предыдущих проходов
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

        self._hold_until = None  # сбросить удержание от предыдущих проходов
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
        self._hold_until = None
        self.clear_current_session()
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
            self._open_timeout = self._button_timeout

    def hold_open(self, duration: Optional[float] = None) -> None:
        """Удерживать турникет открытым пока активны датчики прохода.

        Parameters
        ----------
        duration : float, optional
            Абсолютное время в секундах до которого удерживать открытым.
            Если None, удерживать до явного release_open.
        """
        if duration is None:
            self._hold_until = float("inf")
        else:
            self._hold_until = time() + duration
        logger.debug(f"hold_open: hold_until={self._hold_until}")

    def release_open(self) -> None:
        """Разрешить автоматическое закрытие по таймеру."""
        self._hold_until = None
        logger.debug("release_open: hold released")

    def set_current_session(self, token: Optional[str], user_id: Optional[int] = None) -> None:
        """Привязать текущий проход к токену/пользователю для логирования."""
        self._current_token = token
        self._current_user_id = user_id
        logger.debug(f"set_current_session: token={token}, user_id={user_id}")

    def clear_current_session(self) -> None:
        """Очистить привязку текущего прохода."""
        self._current_token = None
        self._current_user_id = None
        logger.debug("clear_current_session")

    def _cancel_async_tasks(self) -> None:
        """Отменить все отложенные async-задачи TurnstileState."""
        for task in (self._open_task, self._indicator_task, self._deny_beep_task):
            if task and not task.done():
                try:
                    task.cancel()
                except Exception as e:
                    logger.debug(f"_cancel_async_tasks: error cancelling task: {e}")
        self._open_task = None
        self._indicator_task = None
        self._deny_beep_task = None

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

        # В режиме тревоги открытие управляется только set_alarm/clear_alarm
        if self._current_state == TurnstileStateEnum.ALARM:
            logger.debug(f"open_{direction.value}: ignored - alarm active")
            return

        # Игнорировать новую задачу если предыдущая еще выполняется
        if self._open_task and not self._open_task.done():
            logger.debug(f"open_{direction.value}: ignored - previous task still running")
            return

        self._open_task = asyncio.current_task()

        try:
            # Если за время запуска задачи сработала тревога — отменяем открытие
            if self._current_state == TurnstileStateEnum.ALARM:
                logger.debug(f"open_{direction.value}: aborting, alarm active")
                return

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

            # Если сработала тревога за время бипера — выходим
            if self._current_state == TurnstileStateEnum.ALARM:
                logger.debug(f"open_{direction.value}: aborting after beep, alarm active")
                return

            commands = [OutputCommand(name=self._main_buzzer, state=False)]
            event_bus.publish(OutputCommandsGenerated(commands=commands))
            logger.debug(f"open_{direction.value}: beep off")

            # Запустить таймер закрытия если нужно (карта/QR - relay_open_duration)
            if start_timer:
                self._open_since = time()
                self._open_timeout = self._relay_timeout

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

        logger.info(f"close_async: closing turnstile, current_state={self._current_state}")
        # Закрыть реле, выключить индикаторы
        commands = [
            OutputCommand(name=self._entry_relay, state=False),
            OutputCommand(name=self._exit_relay, state=False),
            OutputCommand(name=self._entry_green, state=False),
            OutputCommand(name=self._exit_green, state=False),
            OutputCommand(name=self._entry_red, state=False),
            OutputCommand(name=self._exit_red, state=False),
        ]
        event_bus.publish(OutputCommandsGenerated(commands=commands))

        self._current_state = TurnstileStateEnum.IDLE
        self._open_since = None
        self._hold_until = None
        self.clear_current_session()
        logger.info("close_async: close command published")

    async def _close_after_timeout(self, event_bus, timeout: float) -> None:
        """Асинхронная задача для закрытия через таймаут."""
        from scud_lgtu.domain.common.events.events import OutputCommandsGenerated

        await asyncio.sleep(timeout)

        # Закрыть только если всё еще открыто
        if self._current_state in (TurnstileStateEnum.ENTRY_OPEN, TurnstileStateEnum.EXIT_OPEN):
            commands = [
                OutputCommand(name=self._entry_relay, state=False),
                OutputCommand(name=self._exit_relay, state=False),
                OutputCommand(name=self._entry_green, state=False),
                OutputCommand(name=self._exit_green, state=False),
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
        self._open_since = None
        self._hold_until = None
        self.clear_current_session()
        # Прервать любые отложенные задачи открытия/индикации
        self._cancel_async_tasks()
        self._output_commands = [
            OutputCommand(name=self._entry_relay, state=False),   # Закрыть вход
            OutputCommand(name=self._exit_relay, state=True),     # Открыть выход (эвакуация)
            OutputCommand(name=self._entry_green, state=False),
            OutputCommand(name=self._exit_green, state=False),
            OutputCommand(name=self._entry_red, state=False),
            OutputCommand(name=self._exit_red, state=True),       # Красный индикатор на выходе
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
        self._cancel_async_tasks()
        self._output_commands = [
            OutputCommand(name=self._entry_relay, state=False),
            OutputCommand(name=self._exit_relay, state=False),
            OutputCommand(name=self._entry_green, state=False),
            OutputCommand(name=self._exit_green, state=False),
            OutputCommand(name=self._entry_red, state=False),
            OutputCommand(name=self._exit_red, state=False),
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

        # Автоматическое закрытие после таймаута, только если дверь открыта и нет удержания датчиками
        if self._current_state in (TurnstileStateEnum.ENTRY_OPEN, TurnstileStateEnum.EXIT_OPEN):
            if self._open_since and (now - self._open_since) > self._open_timeout:
                if self._hold_until is None or now > self._hold_until:
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

    @property
    def indicator_duration(self) -> float:
        """Получить длительность индикации."""
        return self._indicator_duration

    @property
    def current_token(self) -> Optional[str]:
        """Токен текущей сессии прохода."""
        return self._current_token

    @property
    def current_user_id(self) -> Optional[int]:
        """user_id текущей сессии прохода."""
        return self._current_user_id

    @property
    def entry_relay(self) -> str:
        """Бизнес-имя реле входа."""
        return self._entry_relay

    @property
    def exit_relay(self) -> str:
        """Бизнес-имя реле выхода."""
        return self._exit_relay
