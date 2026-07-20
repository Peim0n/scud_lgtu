"""GPIO pin mapping."""
from typing import Dict


# Default pin mapping for shift register outputs
# Maps output names to shift register bit positions
DEFAULT_PIN_MAP: Dict[str, int] = {
    "rel1": 0,      # Entry relay
    "rel2": 1,      # Exit relay
    "w1_green": 2,  # Entry green indicator
    "w1_red": 3,    # Entry red indicator
    "w2_green": 4,  # Exit green indicator
    "w2_red": 5,    # Exit red indicator
    "buz": 6,       # Buzzer
    "w1_beep": 7,   # Entry beep
    "w2_beep": 8,   # Exit beep
}


def load_pin_map(config: dict) -> Dict[str, int]:
    """Load pin mapping from configuration."""
    # Extract pin mapping from config
    # This is a placeholder - actual implementation depends on config structure
    return DEFAULT_PIN_MAP.copy()
