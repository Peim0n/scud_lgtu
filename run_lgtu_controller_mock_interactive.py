#!/usr/bin/env python3
"""Запуск LGTU контроллера с mock устройствами и интерактивным управлением."""
import sys
import os
import logging
import threading

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s [%(levelname)s] %(message)s",
)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "scud_lgtu"))

from scud_lgtu.infrastructure.bootstrap import build_application
from scud_lgtu.infrastructure.persistence.event_store import ScudEvent, EventType, EventSource


class InteractiveEventInjector:
    """Интерактивный инжектор событий в очередь движка."""

    def __init__(self, event_queue):
        self._event_queue = event_queue
        self.running = True

    def serial(self, name, data):
        """Инъектить строку из serial/QR-считывателя."""
        self._event_queue.put_nowait(ScudEvent(
            type=EventType.SERIAL_DATA,
            source=EventSource.SERIAL,
            payload={"reader": name, "data": data},
        ))
        print(f"[SERIAL {name}] {data}")

    def card(self, name, card_number, facility_code=1):
        """Инъектить Wiegand-карту."""
        self._event_queue.put_nowait(ScudEvent(
            type=EventType.CARD_READ,
            source=EventSource.WIEGAND,
            payload={
                "reader": name,
                "card_data": card_number,
                "raw_data": card_number,
                "bit_sequence": "0" * 26,
                "is_valid": True,
                "error_message": "",
            },
        ))
        print(f"[CARD {name}] CN={card_number}")

    def gpio(self, pin, value):
        """Инъектить изменение GPIO (mux)."""
        self._event_queue.put_nowait(ScudEvent(
            type=EventType.MUX_CHANGED,
            source=EventSource.MUX,
            payload={"states": {pin: int(value)}},
        ))
        print(f"[GPIO] {pin}={value}")

    def help(self):
        """Показать справку."""
        print("\n=== Команды ===")
        print("serial <name> <data>     - инъектить данные в serial")
        print("card <name> <number>     - инъектить карту")
        print("gpio <pin> <value>       - установить GPIO (0/1)")
        print("help                     - эта справка")
        print("quit                     - выход")

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
                        self.card(parts[1], int(parts[2]))
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


def main():
    """Запуск LGTU контроллера с mock устройствами и интерактивным режимом."""
    print("Запуск LGTU контроллера с mock устройствами и интерактивным управлением...")

    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(script_dir, "scud_lgtu", "config.mock.yml")

    application = build_application(config_path)
    application.start()

    injector = InteractiveEventInjector(application.get_event_queue())
    interactive_thread = threading.Thread(target=injector.run, daemon=True)
    interactive_thread.start()

    try:
        print("\n=== Контроллер запущен ===")
        print("Используйте интерактивный режим для эмуляции устройств.")
        application.run()
    except KeyboardInterrupt:
        print("\nОстановка...")
        injector.running = False
        application.shutdown()
    except Exception as e:
        print(f"Ошибка работы контроллера: {e}")
        import traceback
        traceback.print_exc()
        injector.running = False
        application.shutdown()
        sys.exit(1)


if __name__ == "__main__":
    main()
