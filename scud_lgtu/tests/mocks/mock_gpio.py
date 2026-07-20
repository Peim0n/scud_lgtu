"""Mock GPIO controller for testing without gpiod hardware."""
from typing import Dict, Optional


class MockGPIOController:
    """Mock GPIO controller that simulates gpiod behavior."""
    
    def __init__(self):
        self._lines: Dict[str, MockLine] = {}
        self._mux_addr = 0
    
    def request_line(self, name: str, consumer: str = "test", direction: str = "input") -> "MockLine":
        """Request a GPIO line."""
        if name not in self._lines:
            self._lines[name] = MockLine(name, direction)
        return self._lines[name]
    
    def get_line(self, name: str) -> Optional["MockLine"]:
        """Get existing line."""
        return self._lines.get(name)
    
    def set_line_value(self, name: str, value: int) -> None:
        """Set line value (for output lines)."""
        if name in self._lines:
            self._lines[name].set_value(value)
    
    def get_line_value(self, name: str) -> int:
        """Get line value."""
        if name in self._lines:
            return self._lines[name].get_value()
        return 0
    
    def set_mux_addr(self, addr: int) -> None:
        """Set multiplexer address (no logging)."""
        self._mux_addr = addr
    
    def get_mux_addr(self) -> int:
        """Get current multiplexer address."""
        return self._mux_addr
    
    def cleanup(self) -> None:
        """Cleanup resources."""
        self._lines.clear()


class MockLine:
    """Mock GPIO line."""
    
    def __init__(self, name: str, direction: str = "input"):
        self.name = name
        self.direction = direction
        self._value = 0
        self._consumer = None
    
    def request(self, consumer: str, type: str = "input") -> None:
        """Request the line."""
        self._consumer = consumer
        self.direction = type
    
    def set_value(self, value: int) -> None:
        """Set line value (for output)."""
        if self.direction == "output":
            self._value = value
    
    def get_value(self) -> int:
        """Get line value."""
        return self._value
    
    def release(self) -> None:
        """Release the line."""
        self._consumer = None
