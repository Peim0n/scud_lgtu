"""Адаптер исполнительных механизмов GPIO."""
from scud_lgtu.domain.ports import Actuator
from scud_lgtu.domain.models import OutputCommand
from scud_lgtu.infrastructure.engine import ScudEngine


class ShiftRegisterActuator:
    """Actuator for shift register outputs."""
    
    def __init__(self, engine: ScudEngine, pin_map: dict):
        """Initialize actuator with engine and pin mapping."""
        self._engine = engine
        self._pin_map = pin_map  # Maps output names to shift register pins
    
    def apply(self, command: OutputCommand) -> None:
        """Apply output command to shift register."""
        if command.name not in self._pin_map:
            return
        
        # Convert output command to shift register mask
        # This is a simplified version - actual implementation depends on pin mapping
        pin_offset = self._pin_map[command.name]
        
        # For now, delegate to engine's set_mask (will be improved later)
        # The actual implementation should build the full mask with all pins
        pass
