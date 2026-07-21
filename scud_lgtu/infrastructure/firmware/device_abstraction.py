"""
Абстракции для операций, специфичных для устройств с прошивкой.

Этот модуль определяет интерфейсы для работы с устройствами, имеющими прошивку,
которые могут требовать специальных протоколов или команд.
"""

from typing import Protocol, Optional, Any
from enum import Enum


class DeviceType(str, Enum):
    """Типы устройств."""
    GPIO = "gpio"
    SERIAL = "serial"
    WIEGAND = "wiegand"
    I2C = "i2c"
    SPI = "spi"


class FirmwareInterface(Protocol):
    """Базовый интерфейс для устройств с прошивкой."""

    def initialize(self) -> bool:
        """Инициализировать устройство. Возвращает True при успехе."""
        ...

    def reset(self) -> bool:
        """Сбросить устройство в начальное состояние. Возвращает True при успехе."""
        ...

    def get_status(self) -> dict:
        """Получить статус устройства."""
        ...

    def is_healthy(self) -> bool:
        """Проверить здоровье устройства."""
        ...


class GPIOFirmware(FirmwareInterface):
    """Интерфейс для GPIO-устройств с прошивкой."""

    def configure_pin(self, pin_name: str, mode: str, pull_up: bool = False) -> bool:
        """Сконфигурировать пин."""
        ...

    def read_pin(self, pin_name: str) -> int:
        """Прочитать пин (0 или 1)."""
        ...

    def write_pin(self, pin_name: str, value: int) -> None:
        """Записать значение в пин (0 или 1)."""
        ...


class SerialFirmware(FirmwareInterface):
    """Интерфейс для Serial-устройств с прошивкой."""

    def configure_port(self, port: str, baud: int, timeout: float = 1.0) -> bool:
        """Сконфигурировать serial порт."""
        ...

    def read_line(self) -> Optional[str]:
        """Прочитать строку из порта."""
        ...

    def write_line(self, data: str) -> bool:
        """Записать строку в порт."""
        ...


class WiegandFirmware(FirmwareInterface):
    """Интерфейс для Wiegand-считывателей с прошивкой."""

    def configure_reader(self, d0_pin: str, d1_pin: str, format_type: str) -> bool:
        """Сконфигурировать считыватель."""
        ...

    def enable_encryption(self, key: str) -> bool:
        """Включить шифрование с ключом."""
        ...

    def disable_encryption(self) -> bool:
        """Выключить шифрование."""
        ...
