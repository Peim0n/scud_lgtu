"""
Адаптер Serial firmware интерфейса к BackgroundSerialReader.

Этот модуль реализует интерфейс SerialFirmware используя BackgroundSerialReader.
"""

from scud_lgtu.infrastructure.serial.reader import BackgroundSerialReader
from scud_lgtu.infrastructure.firmware.device_abstraction import SerialFirmware


class SerialAdapter(SerialFirmware):
    """Адаптер BackgroundSerialReader к SerialFirmware интерфейсу."""
    
    def __init__(self, reader: BackgroundSerialReader):
        """
        Инициализировать адаптер с читателем Serial.
        
        Parameters
        ----------
        reader : BackgroundSerialReader
            Инициализированный читатель Serial
        """
        self._reader = reader
    
    def initialize(self) -> bool:
        """Инициализировать устройство."""
        # Читатель уже инициализирован при создании
        return True
    
    def reset(self) -> bool:
        """Сбросить устройство в начальное состояние."""
        try:
            self._reader.stop()
            self._reader.start()
            return True
        except Exception:
            return False
    
    def get_status(self) -> dict:
        """Получить статус устройства."""
        try:
            is_alive = self._reader._thread and self._reader._thread.is_alive()
            return {
                "healthy": is_alive,
                "port": self._reader._port,
                "baud": self._reader._baud,
                "running": is_alive
            }
        except Exception as e:
            return {
                "healthy": False,
                "error": str(e)
            }
    
    def is_healthy(self) -> bool:
        """Проверить здоровье устройства."""
        try:
            return self._reader._thread and self._reader._thread.is_alive()
        except Exception:
            return False
    
    def configure_port(self, port: str, baud: int, timeout: float = 1.0) -> bool:
        """Сконфигурировать serial порт."""
        # Параметры уже заданы при создании читателя
        # Этот метод оставлен для совместимости с интерфейсом
        return True
    
    def read_line(self) -> str:
        """Прочитать строку из порта."""
        # Чтение происходит через очередь в фоне
        # Этот метод оставлен для совместимости с интерфейсом
        raise NotImplementedError("Используйте очередь reader._queue для чтения")
    
    def write_line(self, data: str) -> bool:
        """Записать строку в порт."""
        # Текущая реализация только для чтения
        raise NotImplementedError("Запись в Serial не реализована")
