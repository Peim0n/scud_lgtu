#!/usr/bin/env python3
"""
Скрипт для инъекции событий в работающий контроллер с mock устройствами.

Запускайте в отдельной консоли для тестирования.
"""
import sys
import os
import time
import queue

# Добавляем scud_lgtu в путь
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "scud_lgtu"))

from scud_lgtu.infrastructure.persistence.event_store import ScudEvent, EventType, EventSource


def inject_qr_code(event_queue, url: str):
    """Инъектить QR код."""
    event = ScudEvent(
        type=EventType.QR_READ,
        source=EventSource.SERIAL,
        payload={
            "reader": "serial_Serial-1",
            "data": url
        }
    )
    event_queue.put(event)
    print(f"[INJECT] QR код: {url}")


def inject_card(event_queue, card_data: str, reader: str = "wiegand_Wiegand-1"):
    """Инъектить карточку."""
    event = ScudEvent(
        type=EventType.CARD_READ,
        source=EventSource.WIEGAND,
        payload={
            "reader": reader,
            "card_data": card_data,
            "raw_data": card_data,
            "bit_sequence": "0" * 26,
            "is_valid": True,
            "error_message": ""
        }
    )
    event_queue.put(event)
    print(f"[INJECT] Карточка: {card_data} (reader: {reader})")


def inject_button_press(event_queue, button: str):
    """Инъектить нажатие кнопки."""
    event = ScudEvent(
        type=EventType.MUX_CHANGED,
        source=EventSource.MUX,
        payload={
            "states": {
                button: 0  # Нажата
            }
        }
    )
    event_queue.put(event)
    print(f"[INJECT] Кнопка: {button}")


def inject_passage(event_queue, zone: str, direction: str):
    """Инъектить событие прохода."""
    event = ScudEvent(
        type=EventType.INPUT_SIGNAL,
        source=EventSource.SIGNAL,
        payload={
            "zone": zone,
            "direction": direction,
            "duration": 1.0
        }
    )
    event_queue.put(event)
    print(f"[INJECT] Проход: zone={zone}, direction={direction}")


def inject_alarm(event_queue, active: bool):
    """Инъектить тревогу."""
    event = ScudEvent(
        type=EventType.MUX_CHANGED,
        source=EventSource.MUX,
        payload={
            "states": {
                "alarm": 1 if active else 0
            }
        }
    )
    event_queue.put(event)
    print(f"[INJECT] Тревога: {active}")


def main():
    """Главная функция."""
    print("=== Инъектор событий для LGTU контроллера ===")
    print("Этот скрипт инъектит события напрямую в очередь событий контроллера.")
    print()
    
    # Импортируем после добавления в путь
    from scud_lgtu.infrastructure.bootstrap import build_application
    
    # Загружаем конфигурацию
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(script_dir, "scud_lgtu", "config.yml")
    
    # Создаём приложение для доступа к очереди событий
    # Примечание: это создаст новый экземпляр, но мы получим доступ к очереди
    # через engine, если она глобальная или через механизм IPC
    
    # К сожалению, очереди не разделяются между процессами по умолчанию
    # Поэтому используем другой подход - инъектим через модуль с глобальной очередью
    
    print("ВНИМАНИЕ: Для инъекции событий нужно модифицировать контроллер")
    print("чтобы он использовал multiprocessing.Queue вместо queue.Queue")
    print()
    print("Альтернатива: используйте run_mock_devices_interactive.py")
    print("для интерактивного управления mock устройствами.")
    print()
    print("Примеры команд для run_mock_devices_interactive.py:")
    print("  serial Serial-1 https://pass.lipetsk.ru/test")
    print("  card Wiegand-1 12345")
    print("  gpio button_1 0")


if __name__ == "__main__":
    main()
