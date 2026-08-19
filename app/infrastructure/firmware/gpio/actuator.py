"""Адаптер исполнительных механизмов GPIO (Shift Register)."""
from app.domain.models import OutputCommand
from app.infrastructure.engine import ScudEngine


class ShiftRegisterActuator:
    """Исполнительный механизм для выходов сдвигового регистра."""

    def __init__(self, engine: ScudEngine):
        """Инициализировать актуатор с движком."""
        self._engine = engine

    def apply(self, command: OutputCommand) -> None:
        """Применить команду выхода к сдвиговому регистру."""
        self._engine.set_output_mask({command.name: command.state})
