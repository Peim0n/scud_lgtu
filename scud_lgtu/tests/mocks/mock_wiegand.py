"""Mock Wiegand reader for testing without gpiod hardware."""
from typing import Optional, Callable
from dataclasses import dataclass


@dataclass
class CardData:
    """Mock card data."""
    facility_code: int
    card_number: int
    bits: int
    timestamp: float


class MockWiegandReader:
    """Mock Wiegand reader that simulates gpiod behavior."""
    
    def __init__(
        self,
        d0_pin: str,
        d1_pin: str,
        format_type: str = "era_mf_64_hash",
        bit_timeout: float = 0.025,
        wait_timeout: float = 0.005,
        max_bits: int = 64
    ):
        """Initialize mock Wiegand reader."""
        self.d0_pin = d0_pin
        self.d1_pin = d1_pin
        self.format_type = format_type
        self.bit_timeout = bit_timeout
        self.wait_timeout = wait_timeout
        self.max_bits = max_bits
        
        self._card_callback: Optional[Callable] = None
    
    def set_card_callback(self, callback: Callable) -> None:
        """Set callback for card events."""
        self._card_callback = callback
    
    def start(self) -> None:
        """Start the reader (no-op for mock)."""
        pass
    
    def stop(self) -> None:
        """Stop the reader (no-op for mock)."""
        pass
    
    def inject_card(self, card_number: int, facility_code: int = 1) -> None:
        """Inject a card read event for testing."""
        import time
        card_data = CardData(
            facility_code=facility_code,
            card_number=card_number,
            bits=26,  # Standard 26-bit Wiegand
            timestamp=time.time()
        )
        
        if self._card_callback:
            self._card_callback(card_data)
    
    def is_running(self) -> bool:
        """Check if reader is running (always True for mock)."""
        return True
