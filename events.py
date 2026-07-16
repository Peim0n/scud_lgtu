"""
Событийная модель ScudEngine.

Все hardware-модули публикуют события в одну общую очередь.
Бизнес-логика читает эту очередь и отправляет команды обратно.
"""

from dataclasses import dataclass, field
from typing import Any, Optional
from enum import Enum
import time


class EventType(str, Enum):
    """Типы событий от hardware-модулей."""
    MUX_CHANGED = "mux_changed"
    SHIFT_DONE = "shift_done"
    CARD_READ = "card_read"
    QR_READ = "qr_read"
    SERIAL_DATA = "serial_data"
    INPUT_SIGNAL = "input_signal"
    OUTPUT_STATE = "output_state"
    ERROR = "error"
    HEALTH = "health"
    STOP = "stop"


class EventSource(str, Enum):
    """Источники событий."""
    MUX = "mux"
    SHIFT = "shift"
    WIEGAND = "wiegand"
    SERIAL = "serial"
    SIGNAL = "signal"
    WATCHDOG = "watchdog"
    ENGINE = "engine"


class CommandTarget(str, Enum):
    """Цели команд от бизнес-логики."""
    SHIFT = "shift"
    GPIO = "gpio"
    OUTPUT = "output"
    ENGINE = "engine"


class CommandAction(str, Enum):
    """Действия команд."""
    WRITE_SHIFT = "write_shift"
    SET_PIN = "set_pin"
    SET_OUTPUTS_BULK = "set_outputs_bulk"
    RESET = "reset"
    STOP = "stop"
    GET_STATE = "get_state"


@dataclass(slots=True)
class ScudEvent:
    """Событие от hardware-модуля."""
    type: EventType | str
    source: EventSource | str
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        """Приведение enum-значений к строкам для JSON-сериализации."""
        if isinstance(self.type, Enum):
            self.type = self.type.value
        if isinstance(self.source, Enum):
            self.source = self.source.value


@dataclass(slots=True)
class ScudCommand:
    """Команда от бизнес-логики к hardware-модулю."""
    target: CommandTarget | str
    action: CommandAction | str
    payload: dict[str, Any] = field(default_factory=dict)
    request_id: Optional[str] = None

    def __post_init__(self) -> None:
        """Приведение enum-значений к строкам для JSON-сериализации."""
        if isinstance(self.target, Enum):
            self.target = self.target.value
        if isinstance(self.action, Enum):
            self.action = self.action.value
