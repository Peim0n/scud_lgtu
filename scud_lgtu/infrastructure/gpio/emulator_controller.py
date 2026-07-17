"""
Эмулятор GPIO контроллера для работы без аппаратного обеспечения.

Хранит состояние пинов в памяти и логирует все операции.
Полностью совместим по API с GpiodPinController.
"""
import threading
import logging
from typing import Dict, List, Optional, Tuple, Any

logger = logging.getLogger(__name__)


class EmulatorPinController:
    """
    Эмулятор GPIO контроллера.

    Хранит состояние пинов в памяти без доступа к реальному GPIO.
    Полностью совместим по API с GpiodPinController.
    """

    def __init__(self, pin_map: Optional[Dict[str, Tuple[str, int]]] = None):
        """
        Инициализировать эмулятор контроллер.

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

        # Пины мультиплексора и сдвигового регистра (не логировать операции на них)
        self._mux_pins = {"PA6", "PA11", "PA12", "PA19", "PA7"}

        logger.info("[EmulatorPinController] Initialized")

    def open(self):
        """Открыть контроллер (эмуляция)."""
        with self._lock:
            self._is_open = True
            logger.info("[EmulatorPinController] Controller opened (emulation mode)")

    def close(self):
        """Закрыть контроллер (эмуляция)."""
        with self._lock:
            self._is_open = False
            self._registered_pins.clear()
            self._pin_states.clear()
            self._pin_modes.clear()
            logger.info("[EmulatorPinController] Controller closed")

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
            logger.info(f"[EmulatorPinController] Registered pin: {pin_name} (chip={chip_path}, offset={line_offset})")

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
            logger.info(f"[EmulatorPinController] Set pin modes: {pin_modes}")

    def set_pull_up(self, pin_names: List[str]):
        """
        Включить pull-up (эмуляция - просто логируем).

        Parameters
        ----------
        pin_names : list
            Список имён пинов
        """
        with self._lock:
            for pin_name in pin_names:
                if pin_name in self._registered_pins:
                    pass  # Эмуляция - ничего не делаем
            logger.info(f"[EmulatorPinController] Set pull-up for: {pin_names}")

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
                    if pin_name not in self._mux_pins:
                        logger.info(f"[EmulatorPinController] Set output: {pin_name} = {state}")
            # Логируем только если есть пины не из мультиплексора
            non_mux_states = {k: v for k, v in output_states.items() if k not in self._mux_pins}
            if non_mux_states:
                logger.info(f"[EmulatorPinController] Set output states: {non_mux_states}")

    def set_outputs_bulk(self, output_states: Dict[str, int]):
        """
        Атомарная запись нескольких пинов (эмуляция).

        Parameters
        ----------
        output_states : dict
            {pin_name: 0/1}
        """
        self.set_output_states(output_states)

    def set_outputs_bulk_nolock(self, output_states: Dict[str, int]):
        """
        Атомарная запись нескольких пинов без блокировки (для совместимости).

        Parameters
        ----------
        output_states : dict
            {pin_name: 0/1}
        """
        self.set_outputs_bulk(output_states)

    def write_pin_nolock(self, pin_name: str, value: int):
        """
        Запись одного пина без блокировки (для совместимости).

        Parameters
        ----------
        pin_name : str
            Имя пина
        value : int
            Значение (0 или 1)
        """
        self.write_pin(pin_name, value)

    def read_pin_nolock(self, pin_name: str) -> int:
        """
        Чтение одного пина без блокировки (для совместимости).

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

    def set_drive_strength(self, pin_names: List[str], strength: int):
        """
        Заглушка для совместимости API (эмуляция).

        Parameters
        ----------
        pin_names : list
            Список имён пинов
        strength : int
            Сила драйвера
        """
        logger.info(f"[EmulatorPinController] Set drive strength (emulation): {pin_names} -> {strength}")

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
                if pin_name not in self._mux_pins:
                    logger.info(f"[EmulatorPinController] Write pin: {pin_name} = {value}")

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
            logger.debug(f"[EmulatorPinController] Read pin: {pin_name} = {value}")
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
            logger.debug(f"[EmulatorPinController] Get snapshot: {snapshot}")
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
                    if pin_name not in self._mux_pins:
                        logger.info(f"[EmulatorPinController] Set mask: {pin_name} = {state}")
            # Логируем только если есть пины не из мультиплексора
            non_mux_mask = {k: v for k, v in mask.items() if k not in self._mux_pins}
            if non_mux_mask:
                logger.info(f"[EmulatorPinController] Set mask: {non_mux_mask}")

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

    def set_outputs_bulk_nolock(self, output_states: Dict[str, int]):
        """
        Атомарная запись нескольких пинов без блокировки (для совместимости).

        Parameters
        ----------
        output_states : dict
            {pin_name: 0/1}
        """
        self.set_outputs_bulk(output_states)

    def write_pin_nolock(self, pin_name: str, value: int):
        """
        Запись одного пина без блокировки (для совместимости).

        Parameters
        ----------
        pin_name : str
            Имя пина
        value : int
            Значение (0 или 1)
        """
        self.write_pin(pin_name, value)

    def read_pin_nolock(self, pin_name: str) -> int:
        """
        Чтение одного пина без блокировки (для совместимости).

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

    def set_input_pin(self, pin_name: str, value: int):
        """
        Установить значение входного пина (для симуляции внешних событий).

        Parameters
        ----------
        pin_name : str
            Имя пина
        value : int
            Значение (0 или 1)
        """
        with self._lock:
            if pin_name in self._registered_pins and self._pin_modes[pin_name] == "input":
                self._pin_states[pin_name] = value
                logger.info(f"[EmulatorPinController] Set input pin (simulation): {pin_name} = {value}")

    def get_state(self) -> Dict[str, Any]:
        """
        Получить текущее состояние контроллера.

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
            }

    def print_state(self):
        """Вывести текущее состояние в консоль."""
        state = self.get_state()
        print("\n=== EmulatorPinController State ===")
        print(f"Is open: {state['is_open']}")
        print(f"Registered pins: {state['registered_pins']}")
        print("\nPin states:")
        for pin_name, value in state['pin_states'].items():
            mode = state['pin_modes'].get(pin_name, 'unknown')
            print(f"  {pin_name}: {value} ({mode})")
        print("===================================\n")
