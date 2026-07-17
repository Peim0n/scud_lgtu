"""
Интеграционные тесты с полной эмуляцией оборудования.

Демонстрируют использование MockGpiodPinController, MockSerial и MockWiegandReader
для тестирования логики без реального GPIO и серийных портов.
"""
import pytest
import time
import logging

from scud_lgtu.tests.fixtures.mock_gpio import MockGpiodPinController
from scud_lgtu.tests.fixtures.mock_serial import MockSerial, MockBackgroundSerialReader
from scud_lgtu.tests.fixtures.mock_wiegand import MockWiegandReader, MockWiegandReaderManager
from scud_lgtu.tests.fixtures.mock_engine import MockScudEngine

# Настройка логирования для тестов
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)


class TestMockGpiodPinController:
    """Тесты MockGpiodPinController."""

    def test_gpio_initialization(self):
        """Тест инициализации GPIO контроллера."""
        controller = MockGpiodPinController()
        assert controller.get_state()["is_open"] == False
        logger.info("✓ GPIO контроллер инициализирован")

    def test_gpio_open_close(self):
        """Тест открытия и закрытия GPIO."""
        controller = MockGpiodPinController()
        controller.open()
        assert controller.get_state()["is_open"] == True

        controller.close()
        assert controller.get_state()["is_open"] == False
        logger.info("✓ GPIO open/close работает")

    def test_gpio_context_manager(self):
        """Тест контекстного менеджера."""
        with MockGpiodPinController() as controller:
            assert controller.get_state()["is_open"] == True
        assert controller.get_state()["is_open"] == False
        logger.info("✓ GPIO контекстный менеджер работает")

    def test_gpio_register_pin(self):
        """Тест регистрации пина."""
        controller = MockGpiodPinController()
        controller.open()
        controller.register_pin("PA0", "/dev/gpiochip0", 0)

        state = controller.get_state()
        assert "PA0" in state["registered_pins"]
        assert len(controller.register_calls) == 1
        logger.info("✓ Регистрация пина работает")

    def test_gpio_set_pin_modes(self):
        """Тест настройки режимов пинов."""
        controller = MockGpiodPinController()
        controller.open()
        controller.register_pin("PA0", "/dev/gpiochip0", 0)
        controller.register_pin("PA1", "/dev/gpiochip0", 1)

        controller.set_pin_modes({"PA0": "output", "PA1": "input"})

        state = controller.get_state()
        assert state["pin_modes"]["PA0"] == "output"
        assert state["pin_modes"]["PA1"] == "input"
        logger.info("✓ Настройка режимов пинов работает")

    def test_gpio_write_read(self):
        """Тест записи и чтения пина."""
        controller = MockGpiodPinController()
        controller.open()
        controller.register_pin("PA0", "/dev/gpiochip0", 0)
        controller.set_pin_modes({"PA0": "output"})

        controller.write_pin("PA0", 1)
        assert controller.read_pin("PA0") == 1

        controller.write_pin("PA0", 0)
        assert controller.read_pin("PA0") == 0
        logger.info("✓ Запись/чтение пина работает")

    def test_gpio_set_mask(self):
        """Тест установки маски."""
        controller = MockGpiodPinController()
        controller.open()
        controller.register_pin("PA0", "/dev/gpiochip0", 0)
        controller.register_pin("PA1", "/dev/gpiochip0", 1)
        controller.set_pin_modes({"PA0": "output", "PA1": "output"})

        controller.set_mask({"PA0": True, "PA1": False})

        assert controller.read_pin("PA0") == 1
        assert controller.read_pin("PA1") == 0
        assert len(controller.set_mask_calls) == 1
        logger.info("✓ Установка маски работает")

    def test_gpio_simulate_input_change(self):
        """Тест симуляции изменения входного пина."""
        controller = MockGpiodPinController()
        controller.open()
        controller.register_pin("PA0", "/dev/gpiochip0", 0)
        controller.set_pin_modes({"PA0": "input"})

        controller.simulate_input_change("PA0", 1)
        assert controller.read_pin("PA0") == 1

        controller.simulate_input_change("PA0", 0)
        assert controller.read_pin("PA0") == 0
        logger.info("✓ Симуляция входного пина работает")


class TestMockSerial:
    """Тесты MockSerial."""

    def test_serial_initialization(self):
        """Тест инициализации serial порта."""
        serial = MockSerial(port="/dev/ttyUSB0", baudrate=115200)
        assert serial.port == "/dev/ttyUSB0"
        assert serial.baudrate == 115200
        assert serial.is_open == False
        logger.info("✓ Serial порт инициализирован")

    def test_serial_open_close(self):
        """Тест открытия и закрытия serial."""
        serial = MockSerial(port="/dev/ttyUSB0")
        serial.open()
        assert serial.is_open == True

        serial.close()
        assert serial.is_open == False
        logger.info("✓ Serial open/close работает")

    def test_serial_write_read(self):
        """Тест записи и чтения."""
        serial = MockSerial(port="/dev/ttyUSB0")
        serial.open()

        # Симулируем входящие данные
        serial.simulate_input(b"test data")

        data = serial.readline()
        assert data == b"test data"
        logger.info("✓ Serial write/read работает")

    def test_serial_write_tracking(self):
        """Тест отслеживания записи."""
        serial = MockSerial(port="/dev/ttyUSB0")
        serial.open()

        serial.write(b"test")
        assert len(serial.write_calls) == 1
        assert serial.write_calls[0] == b"test"
        logger.info("✓ Отслеживание записи работает")

    def test_serial_reset(self):
        """Тест сброса состояния."""
        serial = MockSerial(port="/dev/ttyUSB0")
        serial.open()
        serial.write(b"test")
        serial.simulate_input(b"data")

        serial.reset()
        assert len(serial.write_calls) == 0
        assert serial.get_state()["input_queue_size"] == 0
        logger.info("✓ Сброс serial работает")


class TestMockBackgroundSerialReader:
    """Тесты MockBackgroundSerialReader."""

    def test_reader_initialization(self):
        """Тест инициализации reader."""
        reader = MockBackgroundSerialReader(port="/dev/ttyUSB0")
        assert reader.port == "/dev/ttyUSB0"
        assert reader.is_alive() == False
        logger.info("✓ Reader инициализирован")

    def test_reader_start_stop(self):
        """Тест запуска и остановки reader."""
        reader = MockBackgroundSerialReader(port="/dev/ttyUSB0")
        reader.start()
        assert reader.is_alive() == True

        reader.stop()
        time.sleep(0.1)  # Даём время на остановку
        assert reader.is_alive() == False
        logger.info("✓ Reader start/stop работает")

    def test_reader_add_input_line(self):
        """Тест добавления входной строки."""
        reader = MockBackgroundSerialReader(port="/dev/ttyUSB0")
        reader.add_input_line("test line")

        # Запускаем reader
        reader.start()
        time.sleep(0.1)  # Даём время на обработку

        # Проверяем, что строка попала в очередь
        assert not reader.queue.empty()
        line = reader.queue.get()
        assert line == "test line"

        reader.stop()
        logger.info("✓ Добавление входной строки работает")

    def test_reader_multiple_lines(self):
        """Тест обработки нескольких строк."""
        reader = MockBackgroundSerialReader(port="/dev/ttyUSB0")
        reader.add_input_lines(["line1", "line2", "line3"])

        reader.start()
        time.sleep(0.2)  # Даём время на обработку

        # Проверяем, что все строки обработаны
        lines = []
        while not reader.queue.empty():
            lines.append(reader.queue.get())

        assert len(lines) == 3
        assert lines == ["line1", "line2", "line3"]

        reader.stop()
        logger.info("✓ Обработка нескольких строк работает")


class TestMockWiegandReader:
    """Тесты MockWiegandReader."""

    def test_wiegand_initialization(self):
        """Тест инициализации Wiegand reader."""
        reader = MockWiegandReader(reader_id="Wiegand-1")
        assert reader.reader_id == "Wiegand-1"
        assert reader.is_alive() == False
        logger.info("✓ Wiegand reader инициализирован")

    def test_wiegand_start_stop(self):
        """Тест запуска и остановки reader."""
        reader = MockWiegandReader(reader_id="Wiegand-1")
        reader.start()
        assert reader.is_alive() == True

        reader.stop()
        time.sleep(0.1)
        assert reader.is_alive() == False
        logger.info("✓ Wiegand reader start/stop работает")

    def test_wiegand_simulate_card_read(self):
        """Тест симуляции считывания карты."""
        reader = MockWiegandReader(reader_id="Wiegand-1")
        reader.start()
        time.sleep(0.1)

        reader.simulate_card_read("1234567890")
        time.sleep(0.1)

        # Проверяем, что карта считана
        assert not reader.queue.empty()
        card_data = reader.queue.get()
        assert card_data.card_uid == "1234567890"
        assert card_data.reader_id == "Wiegand-1"

        reader.stop()
        logger.info("✓ Симуляция считывания карты работает")

    def test_wiegand_multiple_cards(self):
        """Тест считывания нескольких карт."""
        reader = MockWiegandReader(reader_id="Wiegand-1")
        reader.start()
        time.sleep(0.1)

        reader.simulate_card_reads(["1111111111", "2222222222", "3333333333"])
        time.sleep(0.2)

        # Проверяем, что все карты считаны
        cards = []
        while not reader.queue.empty():
            cards.append(reader.queue.get())

        assert len(cards) == 3
        assert cards[0].card_uid == "1111111111"
        assert cards[1].card_uid == "2222222222"
        assert cards[2].card_uid == "3333333333"

        reader.stop()
        logger.info("✓ Считывание нескольких карт работает")


class TestMockWiegandReaderManager:
    """Тесты MockWiegandReaderManager."""

    def test_manager_initialization(self):
        """Тест инициализации менеджера."""
        manager = MockWiegandReaderManager()
        assert len(manager._readers) == 0
        logger.info("✓ Менеджер инициализирован")

    def test_manager_add_reader(self):
        """Тест добавления reader."""
        manager = MockWiegandReaderManager()
        reader = manager.add_reader("Wiegand-1")

        assert reader is not None
        assert reader.reader_id == "Wiegand-1"
        assert manager.get_reader("Wiegand-1") is not None
        logger.info("✓ Добавление reader работает")

    def test_manager_multiple_readers(self):
        """Тест управления несколькими readers."""
        manager = MockWiegandReaderManager()
        manager.add_reader("Wiegand-1", d0_pin="PA0", d1_pin="PA1")
        manager.add_reader("Wiegand-2", d0_pin="PA2", d1_pin="PA3")

        assert manager.get_reader("Wiegand-1") is not None
        assert manager.get_reader("Wiegand-2") is not None
        logger.info("✓ Управление несколькими readers работает")

    def test_manager_start_stop_all(self):
        """Тест запуска и остановки всех readers."""
        manager = MockWiegandReaderManager()
        manager.add_reader("Wiegand-1")
        manager.add_reader("Wiegand-2")

        manager.start_all()
        time.sleep(0.1)

        assert manager.get_reader("Wiegand-1").is_alive()
        assert manager.get_reader("Wiegand-2").is_alive()

        manager.stop_all()
        time.sleep(0.1)

        assert not manager.get_reader("Wiegand-1").is_alive()
        assert not manager.get_reader("Wiegand-2").is_alive()
        logger.info("✓ Запуск/остановка всех readers работает")

    def test_manager_simulate_card_read(self):
        """Тест симуляции считывания карты через менеджер."""
        manager = MockWiegandReaderManager()
        manager.add_reader("Wiegand-1")
        manager.start_all()
        time.sleep(0.1)

        manager.simulate_card_read("Wiegand-1", "1234567890")
        time.sleep(0.1)

        reader = manager.get_reader("Wiegand-1")
        assert not reader.queue.empty()
        card_data = reader.queue.get()
        assert card_data.card_uid == "1234567890"

        manager.stop_all()
        logger.info("✓ Симуляция через менеджер работает")


class TestMockScudEngine:
    """Тесты MockScudEngine."""

    def test_engine_initialization(self):
        """Тест инициализации engine."""
        engine = MockScudEngine()
        assert engine.gpio_controller is not None
        assert engine.wiegand_manager is not None
        logger.info("✓ Engine инициализирован")

    def test_engine_add_serial_reader(self):
        """Тест добавления serial reader."""
        engine = MockScudEngine()
        reader = engine.add_serial_reader("QR-1", port="/dev/ttyUSB0")

        assert reader is not None
        assert engine.get_serial_reader("QR-1") is not None
        logger.info("✓ Добавление serial reader работает")

    def test_engine_add_wiegand_reader(self):
        """Тест добавления Wiegand reader."""
        engine = MockScudEngine()
        engine.add_wiegand_reader("Wiegand-1", d0_pin="PA0", d1_pin="PA1")

        assert engine.get_wiegand_reader("Wiegand-1") is not None
        logger.info("✓ Добавление Wiegand reader работает")

    def test_engine_start_stop_all_readers(self):
        """Тест запуска и остановки всех readers."""
        engine = MockScudEngine()
        engine.add_serial_reader("QR-1")
        engine.add_wiegand_reader("Wiegand-1")

        engine.start_all_readers()
        time.sleep(0.1)

        assert engine.get_serial_reader("QR-1").is_alive()
        assert engine.get_wiegand_reader("Wiegand-1").is_alive()

        engine.stop_all_readers()
        time.sleep(0.1)

        assert not engine.get_serial_reader("QR-1").is_alive()
        assert not engine.get_wiegand_reader("Wiegand-1").is_alive()
        logger.info("✓ Запуск/остановка всех readers работает")

    def test_engine_simulate_serial_input(self):
        """Тест симуляции serial ввода."""
        engine = MockScudEngine()
        engine.add_serial_reader("QR-1")
        engine.start_all_readers()
        time.sleep(0.1)

        engine.simulate_serial_input("QR-1", "https://pass.lipetsk.ru/...")
        time.sleep(0.1)

        reader = engine.get_serial_reader("QR-1")
        assert not reader.queue.empty()
        line = reader.queue.get()
        assert line == "https://pass.lipetsk.ru/..."

        engine.stop_all_readers()
        logger.info("✓ Симуляция serial ввода работает")

    def test_engine_simulate_card_read(self):
        """Тест симуляции считывания карты."""
        engine = MockScudEngine()
        engine.add_wiegand_reader("Wiegand-1")
        engine.start_all_readers()
        time.sleep(0.1)

        engine.simulate_card_read("Wiegand-1", "1234567890")
        time.sleep(0.1)

        reader = engine.get_wiegand_reader("Wiegand-1")
        assert not reader.queue.empty()
        card_data = reader.queue.get()
        assert card_data.card_uid == "1234567890"

        engine.stop_all_readers()
        logger.info("✓ Симуляция считывания карты работает")

    def test_engine_simulate_gpio_change(self):
        """Тест симуляции изменения GPIO."""
        engine = MockScudEngine()
        engine.gpio_controller.open()
        engine.gpio_controller.register_pin("PA0", "/dev/gpiochip0", 0)
        engine.gpio_controller.set_pin_modes({"PA0": "input"})

        engine.simulate_gpio_change("PA0", 1)
        assert engine.gpio_controller.read_pin("PA0") == 1

        engine.simulate_gpio_change("PA0", 0)
        assert engine.gpio_controller.read_pin("PA0") == 0
        logger.info("✓ Симуляция GPIO работает")

    def test_engine_get_all_states(self):
        """Тест получения состояния всех компонентов."""
        engine = MockScudEngine()
        engine.add_serial_reader("QR-1")
        engine.add_wiegand_reader("Wiegand-1")

        states = engine.get_all_states()
        assert "gpio" in states
        assert "serial_readers" in states
        assert "wiegand_readers" in states
        assert "QR-1" in states["serial_readers"]
        assert "Wiegand-1" in states["wiegand_readers"]
        logger.info("✓ Получение состояния всех компонентов работает")

    def test_engine_reset(self):
        """Тест сброса engine."""
        engine = MockScudEngine()
        engine.add_serial_reader("QR-1")
        engine.add_wiegand_reader("Wiegand-1")
        engine.start_all_readers()
        time.sleep(0.1)

        engine.simulate_card_read("Wiegand-1", "1234567890")
        time.sleep(0.1)

        engine.reset()

        states = engine.get_all_states()
        assert states["mask_calls_count"] == 0
        assert states["queue_puts_count"] == 0
        logger.info("✓ Сброс engine работает")

    def test_engine_cleanup(self):
        """Тест очистки engine."""
        engine = MockScudEngine()
        engine.add_serial_reader("QR-1")
        engine.add_wiegand_reader("Wiegand-1")
        engine.start_all_readers()
        time.sleep(0.1)

        engine.cleanup()

        assert not engine.get_serial_reader("QR-1").is_alive()
        assert not engine.get_wiegand_reader("Wiegand-1").is_alive()
        assert engine.gpio_controller.get_state()["is_open"] == False
        logger.info("✓ Очистка engine работает")


class TestFullMockIntegration:
    """Интеграционные тесты с полной эмуляцией."""

    def test_full_workflow_simulation(self):
        """Тест полной симуляции рабочего процесса."""
        engine = MockScudEngine()

        # Добавляем readers
        engine.add_serial_reader("QR-1", port="/dev/ttyUSB0")
        engine.add_wiegand_reader("Wiegand-1", d0_pin="PA0", d1_pin="PA1")

        # Настраиваем GPIO
        engine.gpio_controller.open()
        engine.gpio_controller.register_pin("PA0", "/dev/gpiochip0", 0)
        engine.gpio_controller.register_pin("PA1", "/dev/gpiochip0", 1)
        engine.gpio_controller.set_pin_modes({"PA0": "input", "PA1": "input"})

        # Запускаем readers
        engine.start_all_readers()
        time.sleep(0.1)

        # Симулируем считывание карты
        engine.simulate_card_read("Wiegand-1", "1234567890")
        time.sleep(0.1)

        # Симулируем QR-код
        engine.simulate_serial_input("QR-1", "https://pass.lipetsk.ru/...")
        time.sleep(0.1)

        # Симулируем изменение GPIO
        engine.simulate_gpio_change("PA0", 1)
        time.sleep(0.05)
        engine.simulate_gpio_change("PA0", 0)

        # Проверяем состояние
        states = engine.get_all_states()
        assert states["wiegand_readers"]["Wiegand-1"]["card_reads_count"] == 1
        assert states["serial_readers"]["QR-1"]["queue_size"] > 0

        # Очищаем
        engine.stop_all_readers()
        engine.cleanup()
        logger.info("✓ Полная симуляция рабочего процесса работает")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
