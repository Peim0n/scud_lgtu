"""
Адаптер GPIO firmware интерфейса к GpiodPinController.

Этот модуль реализует интерфейс GPIOFirmware используя GpiodPinController.
"""

from scud_lgtu.infrastructure.gpio.controller import GpiodPinController
from scud_lgtu.infrastructure.firmware.device_abstraction import GPIOFirmware


class GpiodAdapter(GPIOFirmware):
    """Адаптер GpiodPinController к GPIOFirmware интерфейсу."""
    
    def __init__(self, controller: GpiodPinController):
        """
        Инициализировать адаптер с контроллером GPIO.
        
        Parameters
        ----------
        controller : GpiodPinController
            Инициализированный контроллер GPIO
        """
        self._controller = controller
    
    def initialize(self) -> bool:
        """Инициализировать устройство."""
        # Контроллер уже инициализирован при создании
        return True
    
    def reset(self) -> bool:
        """Сбросить устройство в начальное состояние."""
        try:
            # Сброс всех выходов в 0
            snapshot = self._controller.get_snapshot()
            reset_states = {pin: 0 for pin in snapshot.keys()}
            self._controller.set_output_states(reset_states)
            return True
        except Exception:
            return False
    
    def get_status(self) -> dict:
        """Получить статус устройства."""
        try:
            snapshot = self._controller.get_snapshot()
            return {
                "healthy": True,
                "pins": snapshot,
                "pin_count": len(snapshot)
            }
        except Exception as e:
            return {
                "healthy": False,
                "error": str(e)
            }
    
    def is_healthy(self) -> bool:
        """Проверить здоровье устройства."""
        try:
            self._controller.get_snapshot()
            return True
        except Exception:
            return False
    
    def configure_pin(self, pin_name: str, mode: str, pull_up: bool = False) -> bool:
        """Сконфигурировать пин."""
        try:
            modes = {pin_name: mode}
            pull_ups = [pin_name] if pull_up else []
            self._controller.open(modes, pull_ups=pull_ups)
            return True
        except Exception:
            return False
    
    def read_pin(self, pin_name: str) -> int:
        """Прочитать пин (0 или 1)."""
        return self._controller.read_pin(pin_name)
    
    def write_pin(self, pin_name: str, value: int) -> None:
        """Записать значение в пин (0 или 1)."""
        self._controller.write_pin(pin_name, value)
