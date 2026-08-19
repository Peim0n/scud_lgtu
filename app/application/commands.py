"""Команды приложения для взаимодействия со слоем Infrastructure."""
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


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
    SET_OUTPUT = "set_output"
    RESET = "reset"
    STOP = "stop"
    GET_STATE = "get_state"


@dataclass(slots=True)
class ScudCommand:
    """Команда от бизнес-логики к hardware-модулю."""
    target: CommandTarget | str
    action: CommandAction | str
    payload: dict[str, Any] = field(default_factory=dict)
    request_id: str | None = None

    def __post_init__(self) -> None:
        """Приведение enum-значений к строкам для JSON-сериализации."""
        if isinstance(self.target, Enum):
            self.target = self.target.value
        if isinstance(self.action, Enum):
            self.action = self.action.value
