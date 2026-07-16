"""Thread registry."""
from typing import Dict, Optional, Protocol


class Stoppable(Protocol):
    """Protocol for stoppable threads."""
    
    def start(self) -> None:
        """Start the thread."""
        ...
    
    def stop(self) -> None:
        """Stop the thread."""
        ...
    
    def is_alive(self) -> bool:
        """Check if thread is alive."""
        ...


class ThreadRegistry:
    """Registry for managing all threads."""
    
    def __init__(self):
        """Initialize thread registry."""
        self._threads: Dict[str, Stoppable] = {}
    
    def register(self, name: str, thread: Stoppable) -> None:
        """Register a thread."""
        self._threads[name] = thread
    
    def unregister(self, name: str) -> None:
        """Unregister a thread."""
        if name in self._threads:
            del self._threads[name]
    
    def get(self, name: str) -> Optional[Stoppable]:
        """Get a thread by name."""
        return self._threads.get(name)
    
    def start_all(self) -> None:
        """Start all registered threads."""
        for thread in self._threads.values():
            thread.start()
    
    def stop_all(self, timeout: float = 5.0) -> None:
        """Stop all registered threads."""
        for thread in self._threads.values():
            thread.stop()
    
    def is_healthy(self) -> bool:
        """Check if all threads are healthy."""
        for thread in self._threads.values():
            if not thread.is_alive():
                return False
        return True
