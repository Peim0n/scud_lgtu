#!/usr/bin/env python3
"""
Запуск mock устройств для отладки без реального оборудования.

Этот скрипт запускает mock GPIO, Serial и Wiegand устройства в отдельном процессе,
позволяя инжектить события для тестирования основного приложения.

Использование:
    python run_mock_devices.py

Для инъекции событий используйте методы inject_* в коде или расширьте скрипт.
"""

import sys
import os
import time
import logging

# Добавляем scud_lgtu в путь
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "scud_lgtu"))

from scud_lgtu.tests.mocks.mock_gpio import MockGPIOController
from scud_lgtu.tests.mocks.mock_serial import MockSerialPort
from scud_lgtu.tests.mocks.mock_wiegand import MockWiegandReader
from scud_lgtu.infrastructure.config import load

# Настройка логирования для mock устройств
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [MOCK] %(name)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)


class MockDeviceManager:
    """Менеджер mock устройств."""
    
    def __init__(self, config_path: str = None):
        self.gpio = MockGPIOController()
        self.serial_ports = {}
        self.wiegand_readers = {}
        self.config = self._load_config(config_path)
        self._init_from_config()
    
    def _load_config(self, config_path: str) -> dict:
        """Загрузить конфигурацию."""
        if config_path is None:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            config_path = os.path.join(script_dir, "scud_lgtu", "config.yml")
        return load(config_path)
    
    def _init_from_config(self):
        """Инициализировать устройства из конфигурации."""
        # Инициализация Serial портов
        serial_config = self.config.get("serial", [])
        for serial_cfg in serial_config:
            if isinstance(serial_cfg, dict):
                name = serial_cfg.get("label", f"serial_{len(self.serial_ports)}")
                port = serial_cfg.get("port", "/dev/ttyUSB0")
                baud = serial_cfg.get("baud", 9600)
                self.add_serial_port(name, port, baud)
        
        # Инициализация Wiegand считывателей
        wiegand_config = self.config.get("wiegand", [])
        for wiegand_cfg in wiegand_config:
            if isinstance(wiegand_cfg, dict):
                name = wiegand_cfg.get("label", f"wiegand_{len(self.wiegand_readers)}")
                d0 = wiegand_cfg.get("d0", "PA0")
                d1 = wiegand_cfg.get("d1", "PA1")
                self.add_wiegand_reader(name, d0, d1)
    
    def add_serial_port(self, name: str, port: str = "/dev/ttyUSB0", baudrate: int = 9600):
        """Добавить mock serial порт."""
        self.serial_ports[name] = MockSerialPort(port, baudrate)
        self.serial_ports[name].open()
        logger.info(f"Serial port {name} added: {port} @ {baudrate}")
    
    def add_wiegand_reader(self, name: str, d0_pin: str, d1_pin: str):
        """Добавить mock Wiegand считыватель."""
        self.wiegand_readers[name] = MockWiegandReader(d0_pin, d1_pin)
        self.wiegand_readers[name].start()
        logger.info(f"Wiegand reader {name} added: D0={d0_pin}, D1={d1_pin}")
    
    def inject_serial_data(self, port_name: str, data: str):
        """Инжектить данные в serial порт."""
        if port_name in self.serial_ports:
            self.serial_ports[port_name].inject_data(data.encode())
            logger.info(f"Injected to {port_name}: {data}")
        else:
            logger.warning(f"Serial port {port_name} not found")
    
    def inject_wiegand_card(self, reader_name: str, card_number: int, facility_code: int = 1):
        """Инжектить карточку в Wiegand считыватель."""
        if reader_name in self.wiegand_readers:
            self.wiegand_readers[reader_name].inject_card(card_number, facility_code)
            logger.info(f"Injected card to {reader_name}: FC={facility_code}, CN={card_number}")
        else:
            logger.warning(f"Wiegand reader {reader_name} not found")
    
    def set_gpio_pin(self, pin_name: str, value: int):
        """Установить значение GPIO пина."""
        self.gpio.set_line_value(pin_name, value)
        logger.info(f"GPIO {pin_name} set to {value}")
    
    def stop(self):
        """Остановить все устройства."""
        for port in self.serial_ports.values():
            port.close()
        for reader in self.wiegand_readers.values():
            reader.stop()
        self.gpio.cleanup()
        logger.info("All mock devices stopped")


def main():
    """Главная функция."""
    logger.info("=" * 60)
    logger.info("Mock Devices Manager Started")
    logger.info("=" * 60)
    
    manager = MockDeviceManager()
    
    logger.info(f"Loaded config from: scud_lgtu/config.yml")
    logger.info(f"Serial ports: {list(manager.serial_ports.keys())}")
    logger.info(f"Wiegand readers: {list(manager.wiegand_readers.keys())}")
    logger.info("Mock devices initialized. Press Ctrl+C to stop.")
    logger.info("Available methods:")
    logger.info("  - manager.inject_serial_data('Serial-1', 'test data')")
    logger.info("  - manager.inject_wiegand_card('Wiegand-1', 12345)")
    logger.info("  - manager.set_gpio_pin('button_1', 0)")
    
    try:
        # Пример: инжектим тестовые данные каждые 5 секунд
        # Уберите этот цикл или измените для вашего сценария
        while True:
            time.sleep(5)
            # Пример автоматической инъекции (можно убрать)
            # manager.inject_serial_data("Serial-1", "https://pass.lipetsk.ru/test")
    except KeyboardInterrupt:
        logger.info("Stopping mock devices...")
        manager.stop()
        logger.info("Mock devices stopped.")


if __name__ == "__main__":
    main()
