"""Конечный автомат турникета."""
from enum import Enum
from dataclasses import dataclass
from typing import List, Optional
from time import time
from scud_lgtu.domain.models import OutputCommand
from scud_lgtu.domain.enums import DirectionEnum


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
    
    def __init__(self, auth_timeout: float = 30.0):
        """Инициализировать состояние турникета."""
        self._current_state = TurnstileStateEnum.IDLE
        self._open_since: Optional[float] = None
        self._alarm_since: Optional[float] = None
        self._auth_timeout = auth_timeout
        self._output_commands: List[OutputCommand] = []
    
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
    
    def open_entry(self) -> List[OutputCommand]:
        """Открыть турникет для входа."""
        if not self.can_open(DirectionEnum.IN):
            return []
        
        self._current_state = TurnstileStateEnum.ENTRY_OPEN
        self._open_since = time()
        self._output_commands = [
            OutputCommand(name="rel1", state=True),
            OutputCommand(name="w1_green", state=True),
            OutputCommand(name="w1_red", state=False),
        ]
        return self._output_commands
    
    def open_exit(self) -> List[OutputCommand]:
        """Открыть турникет для выхода."""
        if not self.can_open(DirectionEnum.OUT):
            return []
        
        self._current_state = TurnstileStateEnum.EXIT_OPEN
        self._open_since = time()
        self._output_commands = [
            OutputCommand(name="rel2", state=True),
            OutputCommand(name="w2_green", state=True),
            OutputCommand(name="w2_red", state=False),
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
    
    def set_alarm(self) -> List[OutputCommand]:
        """Установить режим тревоги (пожарная тревога)."""
        if self._current_state == TurnstileStateEnum.ALARM:
            return []
        
        self._current_state = TurnstileStateEnum.ALARM
        self._alarm_since = time()
        self._output_commands = [
            OutputCommand(name="rel1", state=True),
            OutputCommand(name="rel2", state=True),
            OutputCommand(name="w1_red", state=True),
            OutputCommand(name="w2_red", state=True),
        ]
        return self._output_commands
    
    def clear_alarm(self) -> List[OutputCommand]:
        """Сбросить режим тревоги."""
        if self._current_state != TurnstileStateEnum.ALARM:
            return []
        
        self._current_state = TurnstileStateEnum.IDLE
        self._alarm_since = None
        self._output_commands = [
            OutputCommand(name="rel1", state=False),
            OutputCommand(name="rel2", state=False),
            OutputCommand(name="w1_red", state=False),
            OutputCommand(name="w2_red", state=False),
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
        
        return commands
    
    @property
    def current_state(self) -> TurnstileStateEnum:
        """Получить текущее состояние."""
        return self._current_state
    
    @property
    def is_alarm_active(self) -> bool:
        """Проверить, активна ли тревога."""
        return self._current_state == TurnstileStateEnum.ALARM
