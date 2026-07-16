"""Конечный автомат турникета."""
from enum import Enum
from dataclasses import dataclass
from typing import List, Optional
from time import time
from scud_lgtu.domain.models import OutputCommand
from scud_lgtu.domain.enums import DirectionEnum
import logging

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
    
    def __init__(self, auth_timeout: float = 5.0):
        """Инициализировать состояние турникета."""
        self._current_state = TurnstileStateEnum.IDLE
        self._open_since: Optional[float] = None
        self._alarm_since: Optional[float] = None
        self._auth_timeout = auth_timeout
        self._output_commands: List[OutputCommand] = []
        self._beep_since: Optional[float] = None
        self._beep_duration = 0.1  # 100ms beep duration
        self._alarm_beep_since: Optional[float] = None
        self._alarm_beep_on = False
        self._alarm_beep_cycle = 0.5  # 0.5 сек on, 0.5 сек off
        self._deny_beep_count = 0
        self._deny_beep_since: Optional[float] = None
        self._deny_beep_total = 3
        self._deny_beep_duration = 0.1  # 100ms on
        self._deny_beep_pause = 0.1  # 100ms off
        self._deny_beep_state = False  # Текущее состояние бипера для deny beep
    
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
            OutputCommand(name="rel1", state=True),
            OutputCommand(name="w1_green", state=True),
            OutputCommand(name="w1_red", state=False),
            OutputCommand(name="buz", state=True),
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
        
        self._current_state = TurnstileStateEnum.EXIT_OPEN
        if start_timer:
            self._open_since = time()
        else:
            self._open_since = None  # Таймер запускается отдельно при отжатии кнопки
        self._beep_since = time()  # Start beep timer
        self._output_commands = [
            OutputCommand(name="rel2", state=True),
            OutputCommand(name="w2_green", state=True),
            OutputCommand(name="w2_red", state=False),
            OutputCommand(name="buz", state=True),
        ]
        return self._output_commands
    
    def close(self) -> List[OutputCommand]:
        """Закрыть турникет."""
        if self._current_state == TurnstileStateEnum.IDLE:
            return []
        
        self._current_state = TurnstileStateEnum.IDLE
        self._open_since = None
        self._output_commands = [
            OutputCommand(name="rel1", state=False),
            OutputCommand(name="rel2", state=False),
            OutputCommand(name="w1_green", state=False),
            OutputCommand(name="w2_green", state=False),
        ]
        return self._output_commands
    
    def start_open_timer(self) -> None:
        """Запустить таймер закрытия (при отжатии кнопки)."""
        if self._current_state in (TurnstileStateEnum.ENTRY_OPEN, TurnstileStateEnum.EXIT_OPEN):
            self._open_since = time()
    
    def start_deny_beep(self) -> None:
        """Запустить последовательность из 3 коротких писков при отказе в доступе."""
        self._deny_beep_count = 0
        self._deny_beep_since = time()
    
    def set_alarm(self) -> List[OutputCommand]:
        """Установить режим тревоги (пожарная тревога)."""
        if self._current_state == TurnstileStateEnum.ALARM:
            return []
        
        self._current_state = TurnstileStateEnum.ALARM
        self._alarm_since = time()
        self._alarm_beep_since = time()
        self._alarm_beep_on = True
        self._output_commands = [
            OutputCommand(name="rel1", state=True),
            OutputCommand(name="rel2", state=True),
            OutputCommand(name="w1_red", state=True),
            OutputCommand(name="w2_red", state=True),
            OutputCommand(name="buz", state=True),
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
            OutputCommand(name="rel1", state=False),
            OutputCommand(name="rel2", state=False),
            OutputCommand(name="w1_red", state=False),
            OutputCommand(name="w2_red", state=False),
            OutputCommand(name="buz", state=False),
        ]
        return self._output_commands
    
    def block(self) -> List[OutputCommand]:
        """Заблокировать турникет."""
        if self._current_state == TurnstileStateEnum.BLOCKED:
            return []
        
        self._current_state = TurnstileStateEnum.BLOCKED
        self._output_commands = [
            OutputCommand(name="rel1", state=False),
            OutputCommand(name="rel2", state=False),
            OutputCommand(name="w1_red", state=True),
            OutputCommand(name="w2_red", state=True),
        ]
        return self._output_commands
    
    def unblock(self) -> List[OutputCommand]:
        """Разблокировать турникет."""
        if self._current_state != TurnstileStateEnum.BLOCKED:
            return []
        
        self._current_state = TurnstileStateEnum.IDLE
        self._output_commands = [
            OutputCommand(name="w1_red", state=False),
            OutputCommand(name="w2_red", state=False),
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
            commands.append(OutputCommand(name="buz", state=False))
            self._beep_since = None
        
        # Периодический бипер при тревоге (0.5 сек on, 0.5 сек off)
        if self._current_state == TurnstileStateEnum.ALARM and self._alarm_beep_since:
            elapsed = now - self._alarm_beep_since
            if elapsed > self._alarm_beep_cycle:
                # Переключить состояние бипера
                self._alarm_beep_on = not self._alarm_beep_on
                self._alarm_beep_since = now
                commands.append(OutputCommand(name="buz", state=self._alarm_beep_on))
        
        # Последовательность из 3 коротких писков при отказе в доступе
        if self._deny_beep_since and self._deny_beep_count < self._deny_beep_total:
            elapsed = now - self._deny_beep_since
            cycle_duration = self._deny_beep_duration + self._deny_beep_pause
            beep_start = self._deny_beep_count * cycle_duration
            
            logger.debug(f"deny_beep: count={self._deny_beep_count}, elapsed={elapsed:.3f}, beep_start={beep_start:.3f}, current_state={self._deny_beep_state}")
            
            target_state = None
            if elapsed >= beep_start and elapsed < beep_start + self._deny_beep_duration:
                # Включить бипер
                target_state = True
                logger.debug(f"deny_beep: target_state=True (beep {self._deny_beep_count + 1} ON)")
            elif elapsed >= beep_start + self._deny_beep_duration and elapsed < (self._deny_beep_count + 1) * cycle_duration:
                # Выключить бипер
                target_state = False
                logger.debug(f"deny_beep: target_state=False (beep {self._deny_beep_count + 1} OFF)")
            
            # Отправляем команду только если состояние изменилось
            if target_state is not None and target_state != self._deny_beep_state:
                self._deny_beep_state = target_state
                commands.append(OutputCommand(name="buz", state=target_state))
                logger.info(f"deny_beep: sending buz={target_state} for beep {self._deny_beep_count + 1}")
            
            # Переход к следующему писку
            if elapsed >= (self._deny_beep_count + 1) * cycle_duration:
                self._deny_beep_count += 1
                self._deny_beep_state = False  # Сбросить состояние для следующего писка
                logger.debug(f"deny_beep: advanced to count={self._deny_beep_count}, state reset")
                if self._deny_beep_count >= self._deny_beep_total:
                    self._deny_beep_since = None
                    logger.info(f"deny_beep: sequence completed")
        
        return commands
    
    @property
    def current_state(self) -> TurnstileStateEnum:
        """Получить текущее состояние."""
        return self._current_state
    
    @property
    def is_alarm_active(self) -> bool:
        """Проверить, активна ли тревога."""
        return self._current_state == TurnstileStateEnum.ALARM
