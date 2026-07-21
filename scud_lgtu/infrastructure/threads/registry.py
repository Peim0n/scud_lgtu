"""Реестр потоков пакета scud_lgtu.infrastructure.threads."""
from typing import Dict, Optional, Protocol


class Stoppable(Protocol):
    """Протокол для останавливаемых потоков."""

    def start(self) -> None:
        """Запустить поток."""
        ...

    def stop(self) -> None:
        """Остановить поток."""
        ...

    def is_alive(self) -> bool:
        """Проверить, жив ли поток."""
        ...


class ThreadRegistry:
    """Реестр для управления всеми потоками."""

    def __init__(self):
        """Инициализировать реестр потоков."""
        self._threads: Dict[str, Stoppable] = {}

    def register(self, name: str, thread: Stoppable) -> None:
        """Зарегистрировать поток."""
        self._threads[name] = thread

    def unregister(self, name: str) -> None:
        """Удалить поток из реестра."""
        if name in self._threads:
            del self._threads[name]

    def get(self, name: str) -> Optional[Stoppable]:
        """Получить поток по имени."""
        return self._threads.get(name)

    def start_all(self) -> None:
        """Запустить все зарегистрированные потоки."""
        for thread in self._threads.values():
            thread.start()

    def stop_all(self, timeout: float = 5.0) -> None:
        """Остановить все зарегистрированные потоки."""
        for thread in self._threads.values():
            thread.stop()

    def is_healthy(self) -> bool:
        """Проверить, что все потоки здоровы."""
        for thread in self._threads.values():
            if not thread.is_alive():
                return False
        return True
