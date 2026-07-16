"""Mock ScudEngine for testing."""
import queue
from unittest.mock import MagicMock
from typing import Dict, Any


class MockScudEngine:
    """Mock ScudEngine for regression tests."""
    
    def __init__(self):
        self.event_queue = queue.Queue()
        self.cmd_queue = queue.Queue()
        self._cfg = {}
        self._pct = MagicMock()
        self._pct.set_mask = MagicMock()
        self.mask_calls = []  # Track set_mask calls
        self.queue_puts = []  # Track queue.put calls
        
    def set_mask(self, mask: int):
        """Mock set_mask."""
        self.mask_calls.append(mask)
        self._pct.set_mask(mask)
        
    def queue_put(self, event: Any):
        """Mock queue.put."""
        self.queue_puts.append(event)
        self.event_queue.put(event)
        
    def configure(self, config: Dict[str, Any]):
        """Mock configure."""
        self._cfg = config
