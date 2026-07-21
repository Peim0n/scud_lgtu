#!/usr/bin/env python3
"""Запуск LGTU контроллера с mock устройствами (через config.mock.yml)."""
import sys
import os
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s [%(levelname)s] %(message)s",
)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "scud_lgtu"))

from scud_lgtu.infrastructure.bootstrap import build_application


def main():
    """Запуск LGTU контроллера с mock устройствами."""
    print("Запуск LGTU контроллера с mock устройствами...")

    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(script_dir, "scud_lgtu", "config.mock.yml")

    application = build_application(config_path)
    application.start()

    try:
        print("Контроллер запущен. Нажмите Ctrl+C для остановки.")
        application.run()
    except KeyboardInterrupt:
        print("\nОстановка контроллера по запросу пользователя...")
        application.shutdown()
    except Exception as e:
        print(f"Ошибка работы контроллера: {e}")
        import traceback
        traceback.print_exc()
        application.shutdown()
        sys.exit(1)


if __name__ == "__main__":
    main()
