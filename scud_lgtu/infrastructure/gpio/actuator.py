"""Адаптер исполнительных механизмов GPIO (Shift Register)."""
from scud_lgtu.domain.access.ports.ports import Actuator
from scud_lgtu.domain.common.models.models import OutputCommand
from scud_lgtu.infrastructure.core.engine import ScudEngine


class ShiftRegisterActuator:
    """Исполнительный механизм для выходов сдвигового регистра."""

    def __init__(self, engine: ScudEngine):
        """Инициализировать актуатор с движком."""
        self._engine = engine

    def apply(self, command: OutputCommand) -> None:
        """Применить команду выхода к сдвиговому регистру."""
        self._engine.set_output_mask({command.name: command.state})
