"""Event bus for application layer."""
import asyncio
import threading
from typing import Callable, Dict, List, Any
from collections import defaultdict


class EventBus:
    """Event bus for publishing and subscribing to events."""
    
    def __init__(self):
        """Initialize event bus."""
        self._subscribers: Dict[str, List[Callable]] = defaultdict(list)
        self._loop = None
        self._lock = threading.Lock()
    
    def subscribe(self, event_type: str, handler: Callable) -> None:
        """Subscribe to an event type."""
        with self._lock:
            self._subscribers[event_type].append(handler)
    
    def unsubscribe(self, event_type: str, handler: Callable) -> None:
        """Unsubscribe from an event type."""
        with self._lock:
            if event_type in self._subscribers:
                self._subscribers[event_type].remove(handler)
    
    def publish(self, event: Any) -> None:
        """Publish an event to all subscribers."""
        event_type = type(event).__name__
        
        with self._lock:
            handlers = self._subscribers.get(event_type, []).copy()
        
        for handler in handlers:
            try:
                # Check if handler is async
                if asyncio.iscoroutinefunction(handler):
                    # If we have an event loop, schedule it
                    if self._loop and self._loop.is_running():
                        self._loop.call_soon_threadsafe(
                            lambda h=handler, e=event: asyncio.create_task(h(e))
                        )
                else:
                    # Sync handler - call directly
                    handler(event)
            except Exception as e:
                # Log error but don't crash
                print(f"Error in event handler: {e}")
    
    def set_event_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Set the event loop for async handlers."""
        self._loop = loop
