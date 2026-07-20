#!/usr/bin/env python3
"""
Запуск LGTU контроллера с mock устройствами (без реального GPIO и Serial).

Используйте этот скрипт для локальной отладки без оборудования.
"""
import sys
import os
import logging
from unittest.mock import patch, MagicMock

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s [%(levelname)s] %(message)s",
)

# Добавляем scud_lgtu в путь
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "scud_lgtu"))

# Импортируем mock устройства
from scud_lgtu.tests.mocks.mock_gpio import MockGPIOController, MockLine
from scud_lgtu.tests.mocks.mock_serial import MockSerialPort
from scud_lgtu.tests.mocks.mock_wiegand import MockWiegandReader


def mock_gpiod_pin_controller():
    """Создать mock GpiodPinController."""
    mock_ctrl = MagicMock()
    mock_ctrl.open = MagicMock()
    mock_ctrl.close = MagicMock()
    mock_ctrl.write_pin = MagicMock()
    mock_ctrl.set_outputs_bulk = MagicMock()
    mock_ctrl.set_output_states = MagicMock()
    return mock_ctrl


def mock_background_serial_reader(port, baud, retry_delay):
    """Создать mock BackgroundSerialReader."""
    import queue
    mock_reader = MagicMock()
    mock_reader._thread = MagicMock()
    mock_reader._thread.is_alive = MagicMock(return_value=True)
    mock_reader.start = MagicMock(return_value=queue.Queue())
    mock_reader.stop = MagicMock()
    return mock_reader


def mock_weigand_reader_start(*args, **kwargs):
    """Создать mock для WeigandReader.start."""
    import queue
    mock_thread = MagicMock()
    mock_thread.is_alive = MagicMock(return_value=True)
    mock_queue = queue.Queue()
    mock_event = MagicMock()
    mock_event.clear = MagicMock()
    return mock_thread, mock_queue, mock_event


def mock_pin_controller_thread(*args, **kwargs):
    """Создать mock PinControllerThread."""
    import queue
    mock_pct = MagicMock()
    mock_pct._mux_thread = MagicMock()
    mock_pct._mux_thread.is_alive = MagicMock(return_value=True)
    mock_pct._shift_thread = MagicMock()
    mock_pct._shift_thread.is_alive = MagicMock(return_value=True)
    mock_pct.mux_output_queue = queue.Queue()
    mock_pct.shift_input_queue = queue.Queue()
    mock_pct.start = MagicMock()
    mock_pct.stop = MagicMock()
    mock_pct.set_mask = MagicMock()
    return mock_pct


def main():
    """Запуск LGTU контроллера с mock устройствами."""
    print("Запуск LGTU контроллера с mock устройствами...")
    
    # Патчим GpiodPinController
    with patch('scud_lgtu.infrastructure.gpio.controller.GpiodPinController', side_effect=mock_gpiod_pin_controller):
        # Патчим PinControllerThread
        with patch('scud_lgtu.infrastructure.gpio.controller.PinControllerThread', side_effect=mock_pin_controller_thread):
            # Патчим BackgroundSerialReader
            with patch('scud_lgtu.infrastructure.serial.reader.BackgroundSerialReader', side_effect=mock_background_serial_reader):
                # Патчим WeigandReader.start
                with patch('scud_lgtu.infrastructure.serial.wiegand_reader.WeigandReader.start', side_effect=mock_weigand_reader_start):
                    # Импортируем и запускаем основной контроллер
                    from scud_lgtu.infrastructure.bootstrap import build_application
                    
                    # Determine config path
                    script_dir = os.path.dirname(os.path.abspath(__file__))
                    config_path = os.path.join(script_dir, "scud_lgtu", "config.yml")
                    
                    # Build application with DI
                    application = build_application(config_path)
                    
                    # Start engine
                    application._engine.start()
                    
                    try:
                        # Run application
                        print("Контроллер запущен. Нажмите Ctrl+C для остановки.")
                        application.run()
                    except KeyboardInterrupt:
                        print("\nОстановка контроллера по запросу пользователя...")
                        application.stop()
                        application._engine.stop()
                    except Exception as e:
                        print(f"Ошибка работы контроллера: {e}")
                        import traceback
                        traceback.print_exc()
                        application.stop()
                        application._engine.stop()
                        sys.exit(1)


if __name__ == "__main__":
    main()
