"""
Mock ScudEngine для тестирования с полной эмуляцией оборудования.

Использует MockGpiodPinController, MockSerial и MockWiegandReader
для эмуляции работы без реального GPIO и серийных портов.
"""
import queue
import logging
from typing import Dict, Any, Optional
from unittest.mock import MagicMock

from scud_lgtu.tests.fixtures.mock_gpio import MockGpiodPinController
from scud_lgtu.tests.fixtures.mock_serial import MockBackgroundSerialReader
from scud_lgtu.tests.fixtures.mock_wiegand import MockWiegandReaderManager

logger = logging.getLogger(__name__)


class MockScudEngine:
    """
    Mock ScudEngine для интеграционных тестов.

    Эмулирует поведение ScudEngine с использованием mock компонентов:
    - MockGpiodPinController для GPIO
    - MockBackgroundSerialReader для серийных портов
    - MockWiegandReaderManager для считывателей карт
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Инициализировать mock engine.

        Parameters
        ----------
        config : dict, optional
            Конфигурация engine
        """
        self.event_queue = queue.Queue()
        self.cmd_queue = queue.Queue()
        self._cfg = config or {}

        # Mock компоненты
        self.gpio_controller = MockGpiodPinController()
        self.serial_readers: Dict[str, MockBackgroundSerialReader] = {}
        self.wiegand_manager = MockWiegandReaderManager()

        # Mock PinControllerThread
        self._pct = MagicMock()
        self._pct.set_mask = MagicMock()

        # Для отслеживания вызовов
        self.mask_calls = []  # Track set_mask calls
        self.queue_puts = []  # Track queue.put calls

        logger.info("[MockScudEngine] Initialized")

    def configure(self, config: Dict[str, Any]):
        """
        Настроить engine.

        Parameters
        ----------
        config : dict
            Конфигурация
        """
        self._cfg = config
        logger.info("[MockScudEngine] Configured")

    def set_mask(self, mask: int):
        """
        Установить маску (mock).

        Parameters
        ----------
        mask : int
            Маска
        """
        self.mask_calls.append(mask)
        self._pct.set_mask(mask)
        logger.debug(f"[MockScudEngine] Set mask: {mask}")

    def queue_put(self, event: Any):
        """
        Положить событие в очередь (mock).

        Parameters
        ----------
        event : Any
            Событие
        """
        self.queue_puts.append(event)
        self.event_queue.put(event)
        logger.debug(f"[MockScudEngine] Queue put: {event}")

    def add_serial_reader(
        self,
        reader_id: str,
        port: str = "/dev/ttyUSB0",
        baudrate: int = 115200,
        timeout: float = 0.05,
    ) -> MockBackgroundSerialReader:
        """
        Добавить mock serial reader.

        Parameters
        ----------
        reader_id : str
            Идентификатор reader
        port : str
            Путь к порту
        baudrate : int
            Скорость
        timeout : float
            Таймаут

        Returns
        -------
        MockBackgroundSerialReader
            Созданный reader
        """
        reader = MockBackgroundSerialReader(port, baudrate, timeout)
        self.serial_readers[reader_id] = reader
        logger.info(f"[MockScudEngine] Added serial reader: {reader_id} on {port}")
        return reader

    def get_serial_reader(self, reader_id: str) -> Optional[MockBackgroundSerialReader]:
        """
        Получить serial reader по ID.

        Parameters
        ----------
        reader_id : str
            Идентификатор reader

        Returns
        -------
        MockBackgroundSerialReader or None
            Reader или None
        """
        return self.serial_readers.get(reader_id)

    def add_wiegand_reader(
        self,
        reader_id: str,
        d0_pin: str = "PA0",
        d1_pin: str = "PA1",
        bit_timeout: float = 0.025,
        wait_timeout: float = 0.005,
    ):
        """
        Добавить mock Wiegand reader.

        Parameters
        ----------
        reader_id : str
            Идентификатор reader
        d0_pin : str
            Пин D0
        d1_pin : str
            Пин D1
        bit_timeout : float
            Таймаут между битами
        wait_timeout : float
            Таймаут ожидания
        """
        self.wiegand_manager.add_reader(
            reader_id=reader_id,
            d0_pin=d0_pin,
            d1_pin=d1_pin,
            bit_timeout=bit_timeout,
            wait_timeout=wait_timeout,
        )
        logger.info(f"[MockScudEngine] Added Wiegand reader: {reader_id}")

    def get_wiegand_reader(self, reader_id: str):
        """
        Получить Wiegand reader по ID.

        Parameters
        ----------
        reader_id : str
            Идентификатор reader

        Returns
        -------
        MockWiegandReader or None
            Reader или None
        """
        return self.wiegand_manager.get_reader(reader_id)

    def start_all_readers(self):
        """Запустить все readers."""
        # Запустить serial readers
        for reader_id, reader in self.serial_readers.items():
            reader.start()
            logger.info(f"[MockScudEngine] Started serial reader: {reader_id}")

        # Запустить Wiegand readers
        self.wiegand_manager.start_all()
        logger.info("[MockScudEngine] Started all Wiegand readers")

    def stop_all_readers(self, timeout: float = 5.0):
        """
        Остановить все readers.

        Parameters
        ----------
        timeout : float
            Таймаут ожидания
        """
        # Остановить serial readers
        for reader_id, reader in self.serial_readers.items():
            reader.stop(timeout)
            logger.info(f"[MockScudEngine] Stopped serial reader: {reader_id}")

        # Остановить Wiegand readers
        self.wiegand_manager.stop_all(timeout)
        logger.info("[MockScudEngine] Stopped all Wiegand readers")

    def simulate_serial_input(self, reader_id: str, line: str):
        """
        Симулировать входящие данные на serial reader.

        Parameters
        ----------
        reader_id : str
            Идентификатор reader
        line : str
            Строка данных
        """
        reader = self.get_serial_reader(reader_id)
        if reader:
            reader.add_input_line(line)
            logger.info(f"[MockScudEngine] Simulated serial input on {reader_id}: {line}")
        else:
            logger.warning(f"[MockScudEngine] Serial reader {reader_id} not found")

    def simulate_card_read(self, reader_id: str, card_uid: str):
        """
        Симулировать считывание карты.

        Parameters
        ----------
        reader_id : str
            Идентификатор reader
        card_uid : str
            UID карты
        """
        self.wiegand_manager.simulate_card_read(reader_id, card_uid)
        logger.info(f"[MockScudEngine] Simulated card read on {reader_id}: {card_uid}")

    def simulate_gpio_change(self, pin_name: str, value: int):
        """
        Симулировать изменение GPIO пина.

        Parameters
        ----------
        pin_name : str
            Имя пина
        value : int
            Новое значение (0 или 1)
        """
        self.gpio_controller.simulate_input_change(pin_name, value)
        logger.info(f"[MockScudEngine] Simulated GPIO change: {pin_name} = {value}")

    def get_gpio_state(self) -> Dict[str, Any]:
        """
        Получить состояние GPIO контроллера.

        Returns
        -------
        dict
            Состояние GPIO
        """
        return self.gpio_controller.get_state()

    def get_all_states(self) -> Dict[str, Any]:
        """
        Получить состояние всех компонентов.

        Returns
        -------
        dict
            Состояние всех компонентов
        """
        return {
            "gpio": self.gpio_controller.get_state(),
            "serial_readers": {
                reader_id: reader.get_state()
                for reader_id, reader in self.serial_readers.items()
            },
            "wiegand_readers": self.wiegand_manager.get_all_states(),
            "mask_calls_count": len(self.mask_calls),
            "queue_puts_count": len(self.queue_puts),
        }

    def reset(self):
        """Сбросить состояние engine."""
        self.gpio_controller.reset()
        for reader in self.serial_readers.values():
            reader.reset()
        self.wiegand_manager.reset_all()
        self.mask_calls.clear()
        self.queue_puts.clear()
        self.event_queue.queue.clear()
        self.cmd_queue.queue.clear()
        logger.info("[MockScudEngine] Reset")

    def cleanup(self):
        """Очистить ресурсы."""
        self.stop_all_readers()
        self.gpio_controller.close()
        logger.info("[MockScudEngine] Cleanup completed")
