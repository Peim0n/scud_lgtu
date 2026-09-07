"""Адаптер исполнительных механизмов GPIO (Shift Register)."""
from typing import Any

from app.domain.models import OutputCommand


class ShiftRegisterActuator:
    """Исполнительный механизм для выходов сдвигового регистра."""

    def __init__(self, engine: Any):
        """Инициализировать актуатор с движком."""
        self._engine = engine

    def apply(self, command: OutputCommand) -> None:
        """Применить команду выхода к сдвиговому регистру."""
        self._engine.set_output_mask({command.name: command.state})
