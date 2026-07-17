"""
Mock GPIO контроллер для тестирования без аппаратного обеспечения.

Эмулирует поведение GpiodPinController для запуска тестов на любой машине.
"""
import threading
import logging
from typing import Dict, List, Optional, Tuple, Any
from queue import Queue

logger = logging.getLogger(__name__)


class MockGpiodPinController:
    """
    Mock контроллер GPIO для тестирования.

    Эмулирует поведение GpiodPinController без реального GPIO.
    Хранит состояние пинов в памяти и позволяет проверять вызовы методов.
    """

    def __init__(self, pin_map: Optional[Dict[str, Tuple[str, int]]] = None):
        """
        Инициализировать mock контроллер.

        Parameters
        ----------
        pin_map : dict, optional
            Таблица {pin_name: (chip_path, offset)}.
        """
        self.pin_map = pin_map or {}
        self._registered_pins: Dict[str, Any] = {}
        self._pin_states: Dict[str, int] = {}  # pin_name -> 0/1
        self._pin_modes: Dict[str, str] = {}  # pin_name -> "input"/"output"
        self._lock = threading.Lock()
        self._is_open = False

        # Для отслеживания вызовов методов
        self.register_calls: List[Dict[str, Any]] = []
        self.set_mode_calls: List[Dict[str, Any]] = []
        self.set_output_calls: List[Dict[str, Any]] = []
        self.read_calls: List[Dict[str, Any]] = []
        self.set_mask_calls: List[Dict[str, Dict[str, bool]]] = []

    def open(self):
        """Открыть контроллер (mock)."""
        with self._lock:
            self._is_open = True
            logger.info("[MockGpiodPinController] Controller opened")

    def close(self):
        """Закрыть контроллер (mock)."""
        with self._lock:
            self._is_open = False
            self._registered_pins.clear()
            self._pin_states.clear()
            self._pin_modes.clear()
            logger.info("[MockGpiodPinController] Controller closed")

    def __enter__(self):
        """Контекстный менеджер."""
        self.open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Контекстный менеджер."""
        self.close()

    def register_pin(self, pin_name: str, chip_path: str, line_offset: int):
        """
        Зарегистрировать пин для использования.

        Parameters
        ----------
        pin_name : str
            Имя пина
        chip_path : str
            Путь к chip (например, "/dev/gpiochip0")
        line_offset : int
            Смещение линии в chip
        """
        with self._lock:
            self._registered_pins[pin_name] = (chip_path, line_offset)
            self._pin_states[pin_name] = 0  # По умолчанию LOW
            self._pin_modes[pin_name] = "input"  # По умолчанию input
            self.register_calls.append({
                "pin_name": pin_name,
                "chip_path": chip_path,
                "line_offset": line_offset
            })
            logger.debug(f"[MockGpiodPinController] Registered pin: {pin_name}")

    def set_pin_modes(self, pin_modes: Dict[str, str]):
        """
        Настроить направление пинов.

        Parameters
        ----------
        pin_modes : dict
            {pin_name: "input"/"output"}
        """
        with self._lock:
            for pin_name, mode in pin_modes.items():
                if pin_name in self._registered_pins:
                    self._pin_modes[pin_name] = mode
            self.set_mode_calls.append(pin_modes.copy())
            logger.debug(f"[MockGpiodPinController] Set pin modes: {pin_modes}")

    def set_pull_up(self, pin_names: List[str]):
        """
        Включить pull-up (mock).

        Parameters
        ----------
        pin_names : list
            Список имён пинов
        """
        with self._lock:
            for pin_name in pin_names:
                if pin_name in self._registered_pins:
                    # Mock: просто логируем
                    pass
            logger.debug(f"[MockGpiodPinController] Set pull-up for: {pin_names}")

    def set_output_states(self, output_states: Dict[str, int]):
        """
        Выставить уровни на выходных пинах.

        Parameters
        ----------
        output_states : dict
            {pin_name: 0/1}
        """
        with self._lock:
            for pin_name, state in output_states.items():
                if pin_name in self._registered_pins and self._pin_modes[pin_name] == "output":
                    self._pin_states[pin_name] = state
            self.set_output_calls.append(output_states.copy())
            logger.debug(f"[MockGpiodPinController] Set output states: {output_states}")

    def set_outputs_bulk(self, output_states: Dict[str, int]):
        """
        Атомарная запись нескольких пинов (mock).

        Parameters
        ----------
        output_states : dict
            {pin_name: 0/1}
        """
        self.set_output_states(output_states)

    def set_drive_strength(self, pin_names: List[str], strength: int):
        """
        Заглушка для совместимости API (mock).

        Parameters
        ----------
        pin_names : list
            Список имён пинов
        strength : int
            Сила драйвера
        """
        logger.debug(f"[MockGpiodPinController] Set drive strength (mock): {pin_names} -> {strength}")

    def write_pin(self, pin_name: str, value: int):
        """
        Запись одного пина.

        Parameters
        ----------
        pin_name : str
            Имя пина
        value : int
            Значение (0 или 1)
        """
        with self._lock:
            if pin_name in self._registered_pins and self._pin_modes[pin_name] == "output":
                self._pin_states[pin_name] = value
            logger.debug(f"[MockGpiodPinController] Write pin: {pin_name} = {value}")

    def read_pin(self, pin_name: str) -> int:
        """
        Чтение одного пина.

        Parameters
        ----------
        pin_name : str
            Имя пина

        Returns
        -------
        int
            Значение пина (0 или 1)
        """
        with self._lock:
            value = self._pin_states.get(pin_name, 0)
            self.read_calls.append({"pin_name": pin_name, "value": value})
            logger.debug(f"[MockGpiodPinController] Read pin: {pin_name} = {value}")
            return value

    def get_snapshot(self) -> Dict[str, int]:
        """
        Прочитать все зарегистрированные пины.

        Returns
        -------
        dict
            {pin_name: 0/1}
        """
        with self._lock:
            snapshot = self._pin_states.copy()
            logger.debug(f"[MockGpiodPinController] Get snapshot: {snapshot}")
            return snapshot

    def set_mask(self, mask: Dict[str, bool]):
        """
        Установить состояние нескольких пинов по именам.

        Parameters
        ----------
        mask : dict
            {pin_name: True/False}
        """
        with self._lock:
            for pin_name, state in mask.items():
                if pin_name in self._registered_pins and self._pin_modes[pin_name] == "output":
                    self._pin_states[pin_name] = 1 if state else 0
            self.set_mask_calls.append(mask.copy())
            logger.debug(f"[MockGpiodPinController] Set mask: {mask}")

    def set_pin(self, pin_name: str, value: int):
        """
        Установить значение пина (для совместимости с API).

        Parameters
        ----------
        pin_name : str
            Имя пина
        value : int
            Значение (0 или 1)
        """
        self.write_pin(pin_name, value)

    def get_pin(self, pin_name: str) -> int:
        """
        Получить значение пина (для совместимости с API).

        Parameters
        ----------
        pin_name : str
            Имя пина

        Returns
        -------
        int
            Значение пина (0 или 1)
        """
        return self.read_pin(pin_name)

    def simulate_input_change(self, pin_name: str, value: int):
        """
        Симулировать изменение входного пина (для тестов).

        Parameters
        ----------
        pin_name : str
            Имя пина
        value : int
            Новое значение (0 или 1)
        """
        with self._lock:
            if pin_name in self._registered_pins:
                self._pin_states[pin_name] = value
                logger.info(f"[MockGpiodPinController] Simulated input change: {pin_name} = {value}")

    def get_state(self) -> Dict[str, Any]:
        """
        Получить текущее состояние контроллера (для тестов).

        Returns
        -------
        dict
            Состояние контроллера
        """
        with self._lock:
            return {
                "is_open": self._is_open,
                "registered_pins": list(self._registered_pins.keys()),
                "pin_states": self._pin_states.copy(),
                "pin_modes": self._pin_modes.copy(),
                "register_calls_count": len(self.register_calls),
                "set_mode_calls_count": len(self.set_mode_calls),
                "set_output_calls_count": len(self.set_output_calls),
                "read_calls_count": len(self.read_calls),
                "set_mask_calls_count": len(self.set_mask_calls),
            }

    def reset(self):
        """Сбросить состояние контроллера (для тестов)."""
        with self._lock:
            self._registered_pins.clear()
            self._pin_states.clear()
            self._pin_modes.clear()
            self.register_calls.clear()
            self.set_mode_calls.clear()
            self.set_output_calls.clear()
            self.read_calls.clear()
            self.set_mask_calls.clear()
            logger.info("[MockGpiodPinController] Controller reset")
