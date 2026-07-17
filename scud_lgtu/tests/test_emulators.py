"""
Тестирование эмуляторов оборудования.

Проверяет работу EmulatorPinController и EmulatorSerialReader.
"""
import sys
import os
import time
import logging

# Добавляем путь к проекту
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scud_lgtu.infrastructure.gpio.emulator_controller import EmulatorPinController
from scud_lgtu.infrastructure.serial.emulator_reader import EmulatorSerialReader, EmulatorSerialReaderWithQueue
from scud_lgtu.config import load as load_config

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)


def test_gpio_emulator():
    """Тест эмулятора GPIO."""
    logger.info("=== Тест EmulatorPinController ===")

    controller = EmulatorPinController()
    controller.open()

    # Регистрация пинов
    controller.register_pin("PA0", "/dev/gpiochip0", 0)
    controller.register_pin("PA1", "/dev/gpiochip0", 1)
    controller.register_pin("PA6", "/dev/gpiochip0", 6)

    # Настройка режимов
    controller.set_pin_modes({"PA0": "input", "PA1": "output", "PA6": "output"})

    # Тест записи
    controller.write_pin("PA1", 1)
    assert controller.read_pin("PA1") == 1
    logger.info("✓ Запись/чтение пина работает")

    controller.write_pin("PA1", 0)
    assert controller.read_pin("PA1") == 0
    logger.info("✓ Сброс пина работает")

    # Тест маски
    controller.set_mask({"PA1": True, "PA6": False})
    assert controller.read_pin("PA1") == 1
    assert controller.read_pin("PA6") == 0
    logger.info("✓ Установка маски работает")

    # Тест симуляции входного пина
    controller.set_input_pin("PA0", 1)
    assert controller.read_pin("PA0") == 1
    logger.info("✓ Симуляция входного пина работает")

    # Вывод состояния
    controller.print_state()

    controller.close()
    logger.info("=== EmulatorPinController тест пройден ===\n")


def test_serial_emulator_with_queue():
    """Тест эмулятора Serial с очередью (автоматический режим)."""
    logger.info("=== Тест EmulatorSerialReaderWithQueue ===")

    reader = EmulatorSerialReaderWithQueue(port="/dev/ttyUSB0", baudrate=115200)

    # Добавляем тестовые данные
    reader.add_input_lines([
        "https://pass.lipetsk.ru/1234567890",
        "https://pass.lipetsk.ru/0987654321",
        "test_data_3"
    ])

    # Запускаем reader
    reader.start()
    time.sleep(0.2)  # Даём время на обработку

    # Проверяем, что данные прочитаны
    lines = []
    while not reader.queue.empty():
        lines.append(reader.queue.get())

    assert len(lines) == 3
    assert lines[0] == "https://pass.lipetsk.ru/1234567890"
    assert lines[1] == "https://pass.lipetsk.ru/0987654321"
    assert lines[2] == "test_data_3"

    logger.info(f"✓ Прочитано {len(lines)} строк: {lines}")

    reader.stop()
    logger.info("=== EmulatorSerialReaderWithQueue тест пройден ===\n")


def test_config_emulator_mode():
    """Тест загрузки конфига с режимом эмуляции."""
    logger.info("=== Тест конфигурации с эмуляторами ===")

    # Загружаем конфиг
    config_path = os.path.join(os.path.dirname(__file__), "..", "config.yml")
    config = load_config(config_path)

    # Проверяем секцию controller_type
    controller_type = config.get("controller_type", {})
    logger.info(f"controller_type.gpio: {controller_type.get('gpio', 'not set')}")
    logger.info(f"controller_type.serial: {controller_type.get('serial', 'not set')}")

    # Проверяем, что секция существует
    assert "controller_type" in config
    assert "gpio" in controller_type
    assert "serial" in controller_type

    logger.info("✓ Конфигурация содержит секцию controller_type")
    logger.info("=== Конфигурация тест пройден ===\n")


def test_engine_with_emulators():
    """Тест ScudEngine с эмуляторами (упрощённый)."""
    logger.info("=== Тест интеграции эмуляторов ===")

    # Простой тест проверки выбора контроллера
    from scud_lgtu.infrastructure.gpio.controller import GpiodPinController
    from scud_lgtu.infrastructure.gpio.emulator_controller import EmulatorPinController
    from scud_lgtu.infrastructure.serial.reader import BackgroundSerialReader
    from scud_lgtu.infrastructure.serial.emulator_reader import EmulatorSerialReader

    # Проверяем, что оба типа контроллеров существуют
    assert GpiodPinController is not None
    assert EmulatorPinController is not None
    assert BackgroundSerialReader is not None
    assert EmulatorSerialReader is not None

    logger.info("✓ Все классы контроллеров доступны")

    # Проверяем совместимость API эмулятора
    emul_ctrl = EmulatorPinController()

    assert hasattr(emul_ctrl, 'open')
    assert hasattr(emul_ctrl, 'close')
    assert hasattr(emul_ctrl, 'register_pin')
    assert hasattr(emul_ctrl, 'set_pin_modes')
    assert hasattr(emul_ctrl, 'write_pin')
    assert hasattr(emul_ctrl, 'read_pin')
    assert hasattr(emul_ctrl, 'set_mask')

    logger.info("✓ API эмулятора GPIO совместим")

    # Проверяем serial readers
    emul_serial = EmulatorSerialReader("/dev/ttyUSB0")

    assert hasattr(emul_serial, 'start')
    assert hasattr(emul_serial, 'stop')
    assert hasattr(emul_serial, 'is_alive')

    logger.info("✓ API эмулятора Serial совместим")

    logger.info("=== Тест интеграции эмуляторов пройден ===\n")


if __name__ == "__main__":
    logger.info("Запуск тестов эмуляторов...\n")

    try:
        test_gpio_emulator()
        test_serial_emulator_with_queue()
        test_config_emulator_mode()
        test_engine_with_emulators()

        logger.info("\n=== ВСЕ ТЕСТЫ ПРОЙДЕНЫ ===")
        logger.info("Для работы с эмуляторами установите в config.yml:")
        logger.info("  controller_type:")
        logger.info("    gpio: emulator")
        logger.info("    serial: emulator")

    except Exception as e:
        logger.error(f"\n=== ТЕСТЫ ПРОВАЛЕНЫ ===")
        logger.error(f"Ошибка: {e}")
        sys.exit(1)
