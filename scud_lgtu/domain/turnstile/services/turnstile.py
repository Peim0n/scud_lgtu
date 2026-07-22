"""
Конечный автомат турникета системы СКУД.

Состояния:
- IDLE: турникет закрыт
- ENTRY_OPEN: разовое открытие на вход
- EXIT_OPEN: разовое открытие на выход
- UNLOCKED_ENTRY: разблокирован на вход
- UNLOCKED_EXIT: разблокирован на выход
- ALARM: режим тревоги (пожарная тревога)
- BLOCKED: турникет заблокирован

Переходы выполняются синхронно, таймеры обрабатываются в tick().
"""
from enum import Enum
from dataclasses import dataclass
from typing import Dict, List, Optional
from time import time
from scud_lgtu.domain.common.models.models import OutputCommand
from scud_lgtu.domain.common.enums.enums import DirectionEnum
from scud_lgtu.domain.access.ports.ports import ConfigResolver
import logging

logger = logging.getLogger(__name__)


class TurnstileStateEnum(str, Enum):
    """Состояния турникета."""
    IDLE = "idle"
    ENTRY_OPEN = "entry_open"
    EXIT_OPEN = "exit_open"
    UNLOCKED_ENTRY = "unlocked_entry"
    UNLOCKED_EXIT = "unlocked_exit"
    ALARM = "alarm"
    BLOCKED = "blocked"


@dataclass
class TurnstileState:
    """Конечный автомат турникета."""

    def __init__(self, auth_timeout: float, timings: dict, resolver: ConfigResolver):
        self._current_state = TurnstileStateEnum.IDLE
        self._open_since: Optional[float] = None
        self._open_timeout: float = auth_timeout
        self._alarm_since: Optional[float] = None
        self._alarm_beep_since: Optional[float] = None
        self._alarm_beep_on = False
        self._auth_timeout = auth_timeout
        self._output_commands: List[OutputCommand] = []
        self._beep_since: Optional[float] = None
        self._resolver = resolver
        self._hold_until: Optional[float] = None  # удержание открытым по датчикам
        self._current_token: Optional[str] = None
        self._current_user_id: Optional[int] = None

        self._deny_beep_remaining: int = 0
        self._deny_beep_on: bool = False
        self._deny_beep_next_time: Optional[float] = None

        self._indicator_timers: Dict[str, float] = {}

        self._locked_requested: bool = False

        self._load_from_resolver(timings)

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
        self._deny_beep_total = int(self._resolver.get_timing("business", "deny_beep_count", timings["deny_beep_count"]))
        self._open_beep_duration = self._resolver.get_timing("business", "open_beep_duration_s", timings["open_beep_duration_s"])
        self._indicator_duration = self._resolver.get_timing("business", "indicator_duration_s", timings["indicator_duration_s"])
        self._shift_short_press_max = self._resolver.get_timing("turnstile", "shift_short_press_max_s", timings["shift_short_press_max_s"])

        # Отдельные таймауты закрытия: кнопка (после отжатия), карта/QR (после открытия) и задержка после заслона
        self._button_timeout = self._resolver.get_timing("turnstile", "button_timer_duration_s", timings["button_timer_duration_s"])
        self._relay_timeout = self._resolver.get_timing("turnstile", "relay_open_duration_s", timings["relay_open_duration_s"])
        self._post_blockage_safety = self._resolver.get_timing("turnstile", "post_blockage_safety_s", timings["post_blockage_safety_s"])

        self._resolver.set_context("turnstile")
        self._entry_relay = self._resolver.resolve("entry_relay")
        self._exit_relay = self._resolver.resolve("exit_relay")
        self._main_buzzer = self._resolver.resolve("main_buzzer")
        self._entry_green = self._resolver.resolve("entry_green")
        self._entry_red = self._resolver.resolve("entry_red")
        self._exit_green = self._resolver.resolve("exit_green")
        self._exit_red = self._resolver.resolve("exit_red")

        logger.info("[TurnstileState] Конфигурация загружена через ConfigResolver")

    def can_open(self, direction: DirectionEnum) -> bool:
        """Проверить, можно ли открыть турникет в заданном направлении."""
        if self._current_state == TurnstileStateEnum.ALARM:
            return True  # Режим тревоги разрешает любое направление
        if self._current_state == TurnstileStateEnum.BLOCKED:
            return False
        if self._current_state in (
            TurnstileStateEnum.IDLE,
            TurnstileStateEnum.UNLOCKED_ENTRY,
            TurnstileStateEnum.UNLOCKED_EXIT,
        ):
            return True
        if self._current_state in (
            TurnstileStateEnum.ENTRY_OPEN,
            TurnstileStateEnum.EXIT_OPEN,
        ):
            return True
        return False

    def open_entry(self, start_timer: bool = False) -> List[OutputCommand]:
        """Открыть турникет для входа."""
        if not self.can_open(DirectionEnum.IN):
            return []
        if self._current_state == TurnstileStateEnum.ALARM:
            return []

        self._current_state = TurnstileStateEnum.ENTRY_OPEN
        self._hold_until = None
        if start_timer:
            self._open_since = time()
            self._open_timeout = self._relay_timeout
        else:
            self._open_since = None
        self._beep_since = time()
        self._output_commands = [
            OutputCommand(name=self._exit_relay, state=False),
            OutputCommand(name=self._entry_relay, state=True),
            OutputCommand(name=self._entry_green, state=True),
            OutputCommand(name=self._entry_red, state=False),
            OutputCommand(name=self._main_buzzer, state=True),
        ]
        return self._output_commands

    def open_exit(self, start_timer: bool = False) -> List[OutputCommand]:
        """Открыть турникет для выхода."""
        if not self.can_open(DirectionEnum.OUT):
            return []
        if self._current_state == TurnstileStateEnum.ALARM:
            return []

        self._current_state = TurnstileStateEnum.EXIT_OPEN
        self._hold_until = None
        if start_timer:
            self._open_since = time()
            self._open_timeout = self._relay_timeout
        else:
            self._open_since = None
        self._beep_since = time()
        self._output_commands = [
            OutputCommand(name=self._entry_relay, state=False),
            OutputCommand(name=self._exit_relay, state=True),
            OutputCommand(name=self._exit_green, state=True),
            OutputCommand(name=self._exit_red, state=False),
            OutputCommand(name=self._main_buzzer, state=True),
        ]
        return self._output_commands

    def unlock_entry(self) -> List[OutputCommand]:
        """Перевести турникет в режим постоянно открытого входа."""
        if self._current_state in (TurnstileStateEnum.ALARM, TurnstileStateEnum.BLOCKED):
            return []
        self._current_state = TurnstileStateEnum.UNLOCKED_ENTRY
        self._open_since = None
        self._hold_until = None
        self._beep_since = time()
        self._output_commands = [
            OutputCommand(name=self._exit_relay, state=False),
            OutputCommand(name=self._entry_relay, state=True),
            OutputCommand(name=self._entry_green, state=True),
            OutputCommand(name=self._entry_red, state=False),
            OutputCommand(name=self._main_buzzer, state=True),
        ]
        return self._output_commands

    def unlock_exit(self) -> List[OutputCommand]:
        """Перевести турникет в режим постоянно открытого выхода."""
        if self._current_state in (TurnstileStateEnum.ALARM, TurnstileStateEnum.BLOCKED):
            return []
        self._current_state = TurnstileStateEnum.UNLOCKED_EXIT
        self._open_since = None
        self._hold_until = None
        self._beep_since = time()
        self._output_commands = [
            OutputCommand(name=self._entry_relay, state=False),
            OutputCommand(name=self._exit_relay, state=True),
            OutputCommand(name=self._exit_green, state=True),
            OutputCommand(name=self._exit_red, state=False),
            OutputCommand(name=self._main_buzzer, state=True),
        ]
        return self._output_commands

    def close(self) -> List[OutputCommand]:
        """Закрыть турникет (вернуться в IDLE)."""
        if self._current_state in (
            TurnstileStateEnum.IDLE,
            TurnstileStateEnum.ALARM,
            TurnstileStateEnum.BLOCKED,
        ):
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
        """Удерживать турникет открытым."""
        if duration is None:
            self._hold_until = float("inf")
        else:
            self._hold_until = time() + duration
            self._open_since = time()
            self._open_timeout = duration
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

    def deny_beep(self) -> List[OutputCommand]:
        """Запустить последовательность из 3 коротких писков."""
        if self._deny_beep_remaining > 0:
            return []
        self._deny_beep_remaining = self._deny_beep_total
        self._deny_beep_on = True
        self._deny_beep_next_time = time() + self._deny_beep_duration
        return [OutputCommand(name=self._main_buzzer, state=True)]

    def set_indicator(self, name: str, state: bool, duration: Optional[float] = None) -> List[OutputCommand]:
        """Включить/выключить индикатор с опциональным таймером выключения."""
        if duration:
            self._indicator_timers[name] = time() + duration
        else:
            self._indicator_timers.pop(name, None)
        return [OutputCommand(name=name, state=state)]

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
        self._beep_since = None
        self._deny_beep_remaining = 0
        self._deny_beep_on = False
        self._deny_beep_next_time = None
        self._indicator_timers.clear()
        self.clear_current_session()
        self._output_commands = [
            OutputCommand(name=self._entry_relay, state=False),
            OutputCommand(name=self._exit_relay, state=True),
            OutputCommand(name=self._entry_green, state=False),
            OutputCommand(name=self._exit_green, state=False),
            OutputCommand(name=self._entry_red, state=False),
            OutputCommand(name=self._exit_red, state=True),
            OutputCommand(name=self._main_buzzer, state=True),
        ]
        return self._output_commands

    def clear_alarm(self) -> List[OutputCommand]:
        """Сбросить режим тревоги."""
        if self._current_state != TurnstileStateEnum.ALARM:
            return []

        if self._locked_requested:
            self._current_state = TurnstileStateEnum.BLOCKED
        else:
            self._current_state = TurnstileStateEnum.IDLE
        self._alarm_since = None
        self._alarm_beep_since = None
        self._alarm_beep_on = False
        self._open_since = None
        self._hold_until = None
        self._beep_since = None
        self._deny_beep_remaining = 0
        self._deny_beep_on = False
        self._deny_beep_next_time = None
        commands = [
            OutputCommand(name=self._entry_relay, state=False),
            OutputCommand(name=self._exit_relay, state=False),
            OutputCommand(name=self._entry_green, state=False),
            OutputCommand(name=self._exit_green, state=False),
            OutputCommand(name=self._entry_red, state=False),
            OutputCommand(name=self._exit_red, state=False),
            OutputCommand(name=self._main_buzzer, state=False),
        ]
        if self._current_state == TurnstileStateEnum.BLOCKED:
            commands.extend([
                OutputCommand(name=self._entry_red, state=True),
                OutputCommand(name=self._exit_red, state=True),
            ])
        return commands

    def lock(self) -> List[OutputCommand]:
        """Заблокировать турникет."""
        if self._current_state == TurnstileStateEnum.BLOCKED:
            return []

        self._current_state = TurnstileStateEnum.BLOCKED
        self._locked_requested = True
        self._open_since = None
        self._hold_until = None
        self.clear_current_session()
        return [
            OutputCommand(name=self._entry_relay, state=False),
            OutputCommand(name=self._exit_relay, state=False),
            OutputCommand(name=self._entry_green, state=False),
            OutputCommand(name=self._exit_green, state=False),
            OutputCommand(name=self._entry_red, state=True),
            OutputCommand(name=self._exit_red, state=True),
            OutputCommand(name=self._main_buzzer, state=False),
        ]

    def unlock(self) -> List[OutputCommand]:
        """Разблокировать турникет."""
        if self._current_state != TurnstileStateEnum.BLOCKED:
            return []

        self._current_state = TurnstileStateEnum.IDLE
        self._locked_requested = False
        return [
            OutputCommand(name=self._entry_red, state=False),
            OutputCommand(name=self._exit_red, state=False),
        ]

    def tick(self, now: float) -> List[OutputCommand]:
        """Периодический тик для обработки таймаутов."""
        commands: List[OutputCommand] = []

        if self._current_state in (TurnstileStateEnum.ENTRY_OPEN, TurnstileStateEnum.EXIT_OPEN):
            if self._open_since is not None and (now - self._open_since) > self._open_timeout:
                if self._hold_until is None or now > self._hold_until:
                    commands.extend(self.close())

        if self._beep_since is not None and (now - self._beep_since) > self._open_beep_duration:
            if self._deny_beep_remaining == 0:
                commands.append(OutputCommand(name=self._main_buzzer, state=False))
            self._beep_since = None

        if self._deny_beep_remaining > 0 and self._deny_beep_next_time is not None and now >= self._deny_beep_next_time:
            if self._deny_beep_on:
                commands.append(OutputCommand(name=self._main_buzzer, state=False))
                self._deny_beep_remaining -= 1
                if self._deny_beep_remaining > 0:
                    self._deny_beep_on = False
                    self._deny_beep_next_time = now + self._deny_beep_pause
                else:
                    self._deny_beep_on = False
                    self._deny_beep_next_time = None
            else:
                commands.append(OutputCommand(name=self._main_buzzer, state=True))
                self._deny_beep_on = True
                self._deny_beep_next_time = now + self._deny_beep_duration

        expired = [name for name, off_at in self._indicator_timers.items() if now >= off_at]
        for name in expired:
            commands.append(OutputCommand(name=name, state=False))
            del self._indicator_timers[name]

        if self._current_state == TurnstileStateEnum.ALARM and self._alarm_beep_since:
            elapsed = now - self._alarm_beep_since
            if elapsed > self._alarm_beep_cycle:
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

    @property
    def shift_short_press_max(self) -> float:
        """Максимальная длительность короткого нажатия Shift."""
        return self._shift_short_press_max
