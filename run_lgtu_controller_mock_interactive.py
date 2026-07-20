#!/usr/bin/env python3
"""
Запуск LGTU контроллера с mock устройствами и интерактивным управлением.

Этот скрипт:
1. Запускает основной контроллер с mock GPIO/Serial/Wiegand
2. Предоставляет интерактивный интерфейс для эмуляции оборудования
"""
import sys
import os
import logging
import threading
import queue
from unittest.mock import patch, MagicMock

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s [%(levelname)s] %(message)s",
)

# Добавляем scud_lgtu в путь
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "scud_lgtu"))

# Импортируем mock устройства
from scud_lgtu.tests.mocks.mock_gpio import MockGPIOController
from scud_lgtu.tests.mocks.mock_serial import MockSerialPort
from scud_lgtu.tests.mocks.mock_wiegand import MockWiegandReader

# Глобальные mock устройства для доступа из интерактивного режима
mock_gpio = None
mock_serial_ports = {}
mock_wiegand_readers = {}


class InteractiveMockManager:
    """Интерактивный менеджер mock устройств."""
    
    def __init__(self):
        self.running = True
    
    def serial(self, name, data):
        """Инъектить данные в serial."""
        if name in mock_serial_ports:
            mock_serial_ports[name].inject_data(data.encode())
            print(f"[SERIAL {name}] {data}")
        else:
            print(f"ERROR: Serial {name} not found")
    
    def card(self, name, card_number, facility_code=1):
        """Инъектить карточку."""
        if name in mock_wiegand_readers:
            mock_wiegand_readers[name].inject_card(card_number, facility_code)
            print(f"[WIEGAND {name}] FC={facility_code} CN={card_number}")
        else:
            print(f"ERROR: Wiegand {name} not found")
    
    def gpio(self, pin, value):
        """Установить GPIO."""
        if mock_gpio:
            mock_gpio.set_line_value(pin, value)
            print(f"[GPIO] {pin}={value}")
        else:
            print("ERROR: GPIO controller not initialized")
    
    def help(self):
        """Показать справку."""
        print("\n=== Команды ===")
        print("serial <name> <data>     - инъектить данные в serial")
        print("card <name> <number> [fc] - инъектить карточку")
        print("gpio <pin> <value>        - установить GPIO")
        print("help                      - эта справка")
        print("quit                      - выход")
        print("\n=== Доступные устройства ===")
        print(f"Serial: {list(mock_serial_ports.keys())}")
        print(f"Wiegand: {list(mock_wiegand_readers.keys())}")
    
    def run(self):
        """Запустить интерактивный режим."""
        print("\n=== Интерактивный режим mock устройств ===")
        self.help()
        
        while self.running:
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
                    print(f"ERROR: Неизвестная команда: {cmd}")
                    self.help()
            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"ERROR: {e}")
        
        print("Интерактивный режим завершен")


def mock_gpiod_pin_controller():
    """Создать mock GpiodPinController с доступом к глобальному mock_gpio."""
    global mock_gpio
    mock_gpio = MockGPIOController()
    
    mock_ctrl = MagicMock()
    mock_ctrl.open = MagicMock()
    mock_ctrl.close = MagicMock()
    
    # Пины мультиплексора, которые не логируем (постоянно меняются)
    MUX_PINS = {'mux_a0', 'mux_a1', 'mux_a2', 'PA6', 'PA11', 'PA12'}
    
    def log_write_pin(pin, level):
        if pin not in MUX_PINS:
            print(f"[GPIO WRITE] pin={pin}, level={level}")
        mock_gpio.set_line_value(pin, level)
    
    def log_set_outputs_bulk(states):
        # Фильтруем пины мультиплексора
        filtered_states = {k: v for k, v in states.items() if k not in MUX_PINS}
        if filtered_states:
            print(f"[GPIO BULK] states={filtered_states}")
        for pin, level in states.items():
            mock_gpio.set_line_value(pin, level)
    
    def log_set_output_states(states):
        # Фильтруем пины мультиплексора
        filtered_states = {k: v for k, v in states.items() if k not in MUX_PINS}
        if filtered_states:
            print(f"[GPIO OUTPUT STATES] states={filtered_states}")
        for pin, level in states.items():
            mock_gpio.set_line_value(pin, level)
    
    mock_ctrl.write_pin = MagicMock(side_effect=log_write_pin)
    mock_ctrl.set_outputs_bulk = MagicMock(side_effect=log_set_outputs_bulk)
    mock_ctrl.set_output_states = MagicMock(side_effect=log_set_output_states)
    return mock_ctrl


def mock_background_serial_reader(port, baud, retry_delay):
    """Создать mock BackgroundSerialReader с доступом к глобальным mock_serial_ports."""
    global mock_serial_ports
    
    mock_reader = MagicMock()
    mock_port = MockSerialPort(port, baud)
    mock_port.open()
    
    # Используем имя из конфига (Serial-1, Serial-2 и т.д.)
    # Определяем по порту
    if "ttyS1" in port:
        name = "Serial-1"
    elif "ttyS2" in port:
        name = "Serial-2"
    else:
        name = f"Serial-{port.split('/')[-1]}"
    
    mock_serial_ports[name] = mock_port
    
    # Создаем очередь для данных
    data_queue = queue.Queue()
    
    # Запускаем поток для чтения из mock порта
    def read_loop():
        while True:
            try:
                data = mock_port.readline()
                if data:
                    data_queue.put(data.decode())
            except:
                break
    
    read_thread = threading.Thread(target=read_loop, daemon=True)
    read_thread.start()
    
    mock_reader._thread = read_thread
    mock_reader._thread.is_alive = lambda: read_thread.is_alive()
    mock_reader.start = MagicMock(return_value=data_queue)
    mock_reader.stop = MagicMock()
    
    return mock_reader


def mock_weigand_reader_start(d0, d1, wiegand_type, encrypted, decrypt_key, bit_timeout, wait_timeout, ignore_after_valid):
    """Создать mock WeigandReader с доступом к глобальным mock_wiegand_readers."""
    global mock_wiegand_readers
    
    mock_reader = MockWiegandReader(d0, d1)
    
    # Определяем имя по пинам (используем label из конфига)
    # d0 имеет формат "gpiod_controller.wiegand1_d0" -> "Wiegand-1"
    if "wiegand1_d0" in d0 or "wiegand1_d1" in d0:
        name = "Wiegand-1"
    elif "wiegand2_d0" in d0 or "wiegand2_d1" in d0:
        name = "Wiegand-2"
    else:
        name = f"Wiegand-{d0}"
    
    mock_wiegand_readers[name] = mock_reader
    
    mock_thread = MagicMock()
    mock_thread.is_alive = lambda: True
    
    # Создаем очередь для карточек
    card_queue = queue.Queue()
    
    # Устанавливаем callback для передачи карточек в очередь
    def card_callback(card_data):
        from scud_lgtu.infrastructure.serial.wiegand_reader import CardData as RealCardData
        real_card_data = RealCardData(
            card_data.card_number,
            card_data.card_number,  # raw_data
            "0" * 26,  # bit_sequence
            True,  # is_valid
            ""  # error_message
        )
        card_queue.put(real_card_data)
    
    mock_reader.set_card_callback(card_callback)
    
    mock_event = MagicMock()
    mock_event.clear = MagicMock()
    
    return mock_thread, card_queue, mock_event


def mock_pin_controller_thread(*args, **kwargs):
    """Создать mock PinControllerThread."""
    mock_pct = MagicMock()
    mock_pct._mux_thread = MagicMock()
    mock_pct._mux_thread.is_alive = lambda: True
    mock_pct._shift_thread = MagicMock()
    mock_pct._shift_thread.is_alive = lambda: True
    mock_pct.mux_output_queue = queue.Queue()
    mock_pct.shift_input_queue = queue.Queue()
    mock_pct.start = MagicMock()
    mock_pct.stop = MagicMock()
    
    def log_set_mask(masks):
        print(f"[SHIFT REGISTER] Setting masks: {masks}")
        # Конвертируем имена пинов в битовую маску (как в реальном коде)
        # Для простого логирования показываем только имена
        for pin_name, state in masks.items():
            print(f"  {pin_name} = {state}")
    
    mock_pct.set_mask = MagicMock(side_effect=log_set_mask)
    return mock_pct


def main():
    """Запуск LGTU контроллера с mock устройствами и интерактивным режимом."""
    print("Запуск LGTU контроллера с mock устройствами и интерактивным управлением...")
    
    # Патчим все компоненты
    with patch('scud_lgtu.infrastructure.gpio.controller.GpiodPinController', side_effect=mock_gpiod_pin_controller):
        with patch('scud_lgtu.infrastructure.gpio.controller.PinControllerThread', side_effect=mock_pin_controller_thread):
            with patch('scud_lgtu.infrastructure.serial.reader.BackgroundSerialReader', side_effect=mock_background_serial_reader):
                with patch('scud_lgtu.infrastructure.serial.wiegand_reader.WeigandReader.start', side_effect=mock_weigand_reader_start):
                    # Импортируем и запускаем основной контроллер
                    from scud_lgtu.infrastructure.bootstrap import build_application
                    
                    # Determine config path
                    script_dir = os.path.dirname(os.path.abspath(__file__))
                    config_path = os.path.join(script_dir, "scud_lgtu", "config.yml")
                    
                    # Build application with DI
                    application = build_application(config_path)
                    
                    # Start engine (это инициализирует mock устройства)
                    application._engine.start()
                    
                    # Теперь устройства инициализированы, запускаем интерактивный режим
                    print("\n=== Интерактивный режим mock устройств ===")
                    manager = InteractiveMockManager()
                    manager.help()
                    
                    # Запускаем интерактивный менеджер в отдельном потоке
                    interactive_thread = threading.Thread(target=manager.run, daemon=True)
                    interactive_thread.start()
                    
                    try:
                        # Run application
                        print("\n=== Контроллер запущен ===")
                        print("Используйте интерактивный режим для эмуляции устройств.")
                        application.run()
                    except KeyboardInterrupt:
                        print("\nОстановка контроллера...")
                        manager.running = False
                        application.stop()
                        application._engine.stop()
                    except Exception as e:
                        print(f"Ошибка работы контроллера: {e}")
                        import traceback
                        traceback.print_exc()
                        manager.running = False
                        application.stop()
                        application._engine.stop()
                        sys.exit(1)


if __name__ == "__main__":
    main()
