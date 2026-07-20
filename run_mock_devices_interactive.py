#!/usr/bin/env python3
"""
Интерактивный режим mock устройств для отладки.

Запускайте этот скрипт в отдельной консоли для интерактивного управления mock устройствами.
"""

import sys
import os
import time
import logging

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "scud_lgtu"))

from scud_lgtu.tests.mocks.mock_gpio import MockGPIOController
from scud_lgtu.tests.mocks.mock_serial import MockSerialPort
from scud_lgtu.tests.mocks.mock_wiegand import MockWiegandReader
from scud_lgtu.infrastructure.config import load

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [MOCK] %(message)s",
)

logger = logging.getLogger(__name__)


class InteractiveMockManager:
    """Интерактивный менеджер mock устройств."""
    
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
                self.add_serial(name, port, baud)
        
        # Инициализация Wiegand считывателей
        wiegand_config = self.config.get("wiegand", [])
        for wiegand_cfg in wiegand_config:
            if isinstance(wiegand_cfg, dict):
                name = wiegand_cfg.get("label", f"wiegand_{len(self.wiegand_readers)}")
                d0 = wiegand_cfg.get("d0", "PA0")
                d1 = wiegand_cfg.get("d1", "PA1")
                self.add_wiegand(name, d0, d1)
    
    def add_serial(self, name, port, baudrate):
        self.serial_ports[name] = MockSerialPort(port, baudrate)
        self.serial_ports[name].open()
        logger.info(f"Serial {name} added: {port} @ {baudrate}")
    
    def add_wiegand(self, name, d0, d1):
        self.wiegand_readers[name] = MockWiegandReader(d0, d1)
        self.wiegand_readers[name].start()
        logger.info(f"Wiegand {name} added: D0={d0}, D1={d1}")
    
    def serial(self, name, data):
        """Инжектить данные в serial."""
        if name in self.serial_ports:
            self.serial_ports[name].inject_data(data.encode())
            logger.info(f"[SERIAL {name}] {data}")
        else:
            logger.error(f"Serial {name} not found")
    
    def card(self, name, card_number, facility_code=1):
        """Инжектить карточку."""
        if name in self.wiegand_readers:
            self.wiegand_readers[name].inject_card(card_number, facility_code)
            logger.info(f"[WIEGAND {name}] FC={facility_code} CN={card_number}")
        else:
            logger.error(f"Wiegand {name} not found")
    
    def gpio(self, pin, value):
        """Установить GPIO."""
        self.gpio.set_line_value(pin, value)
        logger.info(f"[GPIO] {pin}={value}")
    
    def help(self):
        """Показать справку."""
        print("\n=== Команды ===")
        print("serial <name> <data>     - инжектить данные в serial")
        print("card <name> <number> [fc] - инжектить карточку")
        print("gpio <pin> <value>        - установить GPIO")
        print("help                      - эта справка")
        print("quit                      - выход")
        print("\n=== Доступные устройства ===")
        print(f"Serial: {list(self.serial_ports.keys())}")
        print(f"Wiegand: {list(self.wiegand_readers.keys())}")
    
    def run(self):
        """Запустить интерактивный режим."""
        logger.info("Интерактивный режим mock устройств")
        logger.info(f"Загружен конфиг: scud_lgtu/config.yml")
        self.help()
        
        while True:
            try:
                cmd = input("\n> ").strip()
                if not cmd:
                    continue
                if cmd == "quit":
                    break
                elif cmd == "help":
                    self.help()
                elif cmd.startswith("serial "):
                    parts = cmd.split(" ", 2)
                    if len(parts) == 3:
                        self.serial(parts[1], parts[2])
                elif cmd.startswith("card "):
                    parts = cmd.split()
                    if len(parts) >= 3:
                        fc = int(parts[3]) if len(parts) > 3 else 1
                        self.card(parts[1], int(parts[2]), fc)
                elif cmd.startswith("gpio "):
                    parts = cmd.split()
                    if len(parts) == 3:
                        self.gpio(parts[1], int(parts[2]))
                else:
                    logger.error(f"Неизвестная команда: {cmd}")
                    self.help()
            except KeyboardInterrupt:
                break
            except Exception as e:
                logger.error(f"Ошибка: {e}")
        
        logger.info("Остановка...")


if __name__ == "__main__":
    manager = InteractiveMockManager()
    manager.run()
