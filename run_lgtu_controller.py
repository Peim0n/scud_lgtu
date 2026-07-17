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

from scud_lgtu.bootstrap import build_application


def main():
    """Запуск LGTU контроллера."""
    print("Запуск LGTU контроллера...")
    
    # Determine config path
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(script_dir, "scud_lgtu", "config.yml")
    
    # Build application with DI
    application = build_application(config_path)
    
    # Start engine
    application._engine.start()
    
    try:
        # Run application
        application.run()
    except KeyboardInterrupt:
        print("\nОстановка контроллера по запросу пользователя...")
        application.stop()
        application._engine.stop()
    except Exception as e:
        print(f"Ошибка работы контроллера: {e}")
        application.stop()
        application._engine.stop()
        sys.exit(1)


if __name__ == "__main__":
    main()
