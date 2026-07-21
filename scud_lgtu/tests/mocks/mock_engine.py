"""Мок ScudEngine для запуска без реального железа."""
import queue
import threading
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


class MockEngine:
    """Заглушка ScudEngine, возвращающая пустую очередь событий."""

    def __init__(self, config: dict, timings: Optional[dict] = None) -> None:
        self._config = config
        self._timings = timings or {}
        self._event_queue: queue.Queue = queue.Queue()
        self._cmd_queue: queue.Queue = queue.Queue()
        self._stop_event = threading.Event()
        self._started = False

    def start(self) -> None:
        """Запуск mock-движка."""
        if self._started:
            return
        self._started = True
        logger.info("MockEngine: запущен")

    def stop(self) -> None:
        """Остановка mock-движка."""
        self._stop_event.set()
        self._started = False
        logger.info("MockEngine: остановлен")

    def is_healthy(self) -> bool:
        """Мок всегда здоров."""
        return self._started

    def get_event_queue(self) -> queue.Queue:
        """Вернуть очередь событий."""
        return self._event_queue

    def get_command_queue(self) -> queue.Queue:
        """Вернуть очередь команд."""
        return self._cmd_queue

    def set_output_mask(self, masks: dict[str, bool]) -> None:
        """Принять маску выходов (mock)."""
        logger.info(f"MockEngine: set_output_mask {masks}")

    def send_command(self, command: Any) -> None:
        """Принять команду (mock)."""
        self._cmd_queue.put(command)
