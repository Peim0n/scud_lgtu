"""
Адаптер Wiegand firmware интерфейса к WeigandReader.

Этот модуль реализует интерфейс WiegandFirmware используя WeigandReader.
"""

from scud_lgtu.infrastructure.serial.wiegand_reader import WeigandReader
from scud_lgtu.infrastructure.firmware.device_abstraction import WiegandFirmware


class WiegandAdapter(WiegandFirmware):
    """Адаптер WeigandReader к WiegandFirmware интерфейсу."""
    
    def __init__(self, reader: WeigandReader):
        """
        Инициализировать адаптер с читателем Wiegand.
        
        Parameters
        ----------
        reader : WeigandReader
            Инициализированный читатель Wiegand
        """
        self._reader = reader
    
    def initialize(self) -> bool:
        """Инициализировать устройство."""
        try:
            self._reader.open()
            return True
        except Exception:
            return False
    
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
            is_alive = hasattr(self._reader, '_thread') and self._reader._thread and self._reader._thread.is_alive()
            return {
                "healthy": is_alive,
                "chip_path": self._reader.chip_path,
                "d0_offset": self._reader.d0_offset,
                "d1_offset": self._reader.d1_offset,
                "total_bits": self._reader.total_bits,
                "encrypted": self._reader.encrypted,
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
            return hasattr(self._reader, '_thread') and self._reader._thread and self._reader._thread.is_alive()
        except Exception:
            return False
    
    def configure_reader(self, d0_pin: str, d1_pin: str, format_type: str) -> bool:
        """Сконфигурировать считыватель."""
        # Параметры уже заданы при создании читателя
        # Этот метод оставлен для совместимости с интерфейсом
        return True
    
    def enable_encryption(self, key: str) -> bool:
        """Включить шифрование с ключом."""
        # Шифрование настраивается при создании читателя
        # Этот метод оставлен для совместимости с интерфейсом
        return False
    
    def disable_encryption(self) -> bool:
        """Выключить шифрование."""
        # Шифрование настраивается при создании читателя
        # Этот метод оставлен для совместимости с интерфейсом
        return False
