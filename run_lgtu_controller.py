#!/usr/bin/env python3
"""
Запуск LGTU контроллера турникета для системы управления доступом.
"""

import logging
import sys
import os

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s [%(levelname)s] %(message)s",
)

from scud_lgtu.infrastructure.bootstrap import build_application


def main():
    """Запуск LGTU контроллера."""
    print("Запуск LGTU контроллера...")
    
    # Определить путь к конфигурации
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(script_dir, "scud_lgtu", "config.yml")
    
    # Собрать приложение с DI
    application = build_application(config_path)
    
    # Запустить движок
    application.start()
    
    try:
        # Запустить приложение
        application.run()
    except KeyboardInterrupt:
        print("\nОстановка контроллера по запросу пользователя...")
        application.shutdown()
    except Exception as e:
        print(f"Ошибка работы контроллера: {e}")
        application.shutdown()
        sys.exit(1)


if __name__ == "__main__":
    main()
