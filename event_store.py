"""
Хранилище событий проходов.

Собирает события локально и выгружает их бэкенду при возможности.
"""

import threading

from .models import PassageEvent


class EventStore:
    """
    Локальное хранилище событий.

    Потокобезопасное in-memory хранилище. В production — SQLite с ротацией.
    """

    def __init__(self) -> None:
        """Создать потокобезопасное in-memory хранилище событий."""
        self._events: list[PassageEvent] = []
        self._lock = threading.Lock()

    def append(self, event: PassageEvent) -> None:
        """Добавить событие в хранилище."""
        with self._lock:
            self._events.append(event)

    def flush(self) -> list[PassageEvent]:
        """Извлечь все накопленные события и очистить хранилище."""
        with self._lock:
            events = self._events
            self._events = []
        return events

    def count(self) -> int:
        """Текущее количество событий в хранилище."""
        with self._lock:
            return len(self._events)
