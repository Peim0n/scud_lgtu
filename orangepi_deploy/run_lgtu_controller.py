#!/usr/bin/env python3
"""
Запуск LGTU контроллера турникета для системы управления доступом.
"""

import logging
import sys

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s [%(levelname)s] %(message)s",
)

from scud_lgtu.engine import ScudEngine
import scud_lgtu.config as config


def main():
    """Запуск LGTU контроллера."""
    print("Запуск LGTU контроллера...")
    
    # Загрузка конфигурации
    cfg = config.load()
    
    # Создание и запуск движка
    engine = ScudEngine()
    engine.start()
    
    try:
        # Запуск LGTU контроллера
        engine.run_lgtu_controller()
    except KeyboardInterrupt:
        print("\nОстановка контроллера по запросу пользователя...")
        engine.stop()
    except Exception as e:
        print(f"Ошибка работы контроллера: {e}")
        engine.stop()
        sys.exit(1)


if __name__ == "__main__":
    main()
