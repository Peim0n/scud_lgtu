"""Event bus for application layer."""
import asyncio
import threading
from typing import Callable, Dict, List, Any
from collections import defaultdict


class EventBus:
    """Event bus for publishing and subscribing to events."""
    
    def __init__(self, turnstile=None):
        """Initialize event bus."""
        self._subscribers: Dict[str, List[Callable]] = defaultdict(list)
        self._loop = None
        self._lock = threading.Lock()
        self._turnstile = turnstile  # Для проверки состояния тревоги
    
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
        
        # Во время тревоги игнорировать все события кроме PassageDetected (датчики)
        if self._turnstile and self._turnstile._current_state == "ALARM":
            if event_type != "PassageDetected":
                return  # Игнорировать все события кроме датчиков
        
        with self._lock:
            handlers = self._subscribers.get(event_type, []).copy()
        
        for handler in handlers:
            try:
                # Call the handler and check if result is a coroutine
                result = handler(event)
                
                if asyncio.iscoroutine(result):
                    # If result is a coroutine, schedule it as a task
                    if self._loop and self._loop.is_running():
                        self._loop.call_soon_threadsafe(
                            lambda c=result: asyncio.create_task(c)
                        )
                # If result is not a coroutine, it was a sync handler that already executed
            except Exception as e:
                # Log error but don't crash
                print(f"Error in event handler: {e}")
    
    def set_event_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Set the event loop for async handlers."""
        self._loop = loop
