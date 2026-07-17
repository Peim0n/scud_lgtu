#!/usr/bin/env python3
"""
Скрипт для тестирования эмуляторов оборудования.

Позволяет симулировать ввод QR-кодов и карт в работающую систему.
"""
import sys
import time
from scud_lgtu.infrastructure.serial.emulator_wiegand import EmulatorWiegandReader

def main():
    print("=== Тестирование эмуляторов ===")
    print("1. QR-коды вводятся прямо в консоль работающего приложения")
    print("2. Для симуляции карт можно использовать этот скрипт")
    print()
    
    # Создаём эмулятор Wiegand reader для тестирования
    reader = EmulatorWiegandReader(
        reader_id="Wiegand-1",
        console_input=True  # Включаем консольный ввод
    )
    
    print("Запуск эмулятора Wiegand reader...")
    print("Введите UID карты (например: 1234567890) и нажмите Enter:")
    print("Для выхода введите 'quit' или Ctrl+C")
    print()
    
    try:
        reader.start()
        
        # В этом скрипте поток будет читать из stdin
        while reader.is_alive():
            time.sleep(0.1)
            
    except KeyboardInterrupt:
        print("\nПрерывание пользователем...")
    finally:
        reader.stop()
        print("Эмулятор остановлен")

if __name__ == "__main__":
    main()
