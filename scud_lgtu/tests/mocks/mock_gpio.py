"""Мок gpio пакета scud_lgtu.tests.mocks."""
from typing import Dict, Optional


class MockGPIOController:
    """Мок контроллера GPIO, имитирующий поведение gpiod."""

    def __init__(self):
        self._lines: Dict[str, MockLine] = {}
        self._mux_addr = 0

    def request_line(self, name: str, consumer: str = "test", direction: str = "input") -> "MockLine":
        """Запросить линию GPIO."""
        if name not in self._lines:
            self._lines[name] = MockLine(name, direction)
        return self._lines[name]

    def get_line(self, name: str) -> Optional["MockLine"]:
        """Получить существующую линию."""
        return self._lines.get(name)

    def set_line_value(self, name: str, value: int) -> None:
        """Установить значение линии (для выходов)."""
        if name in self._lines:
            self._lines[name].set_value(value)

    def get_line_value(self, name: str) -> int:
        """Получить значение линии."""
        if name in self._lines:
            return self._lines[name].get_value()
        return 0

    def set_mux_addr(self, addr: int) -> None:
        """Установить адрес мультиплексора (без логирования)."""
        self._mux_addr = addr

    def get_mux_addr(self) -> int:
        """Получить текущий адрес мультиплексора."""
        return self._mux_addr

    def cleanup(self) -> None:
        """Освободить ресурсы."""
        self._lines.clear()


class MockLine:
    """Мок линии GPIO."""

    def __init__(self, name: str, direction: str = "input"):
        self.name = name
        self.direction = direction
        self._value = 0
        self._consumer = None

    def request(self, consumer: str, type: str = "input") -> None:
        """Запросить линию."""
        self._consumer = consumer
        self.direction = type

    def set_value(self, value: int) -> None:
        """Установить значение линии (для выхода)."""
        if self.direction == "output":
            self._value = value

    def get_value(self) -> int:
        """Получить значение линии."""
        return self._value

    def release(self) -> None:
        """Освободить линию."""
        self._consumer = None
