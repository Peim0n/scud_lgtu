#!/usr/bin/env python3
"""
Запуск LGTU контроллера турникета для системы управления доступом.
"""

import ctypes
import logging
import os
import sys
import threading


def _set_os_thread_name() -> None:
    if sys.platform != "linux":
        return
    try:
        name = threading.current_thread().name.encode("utf-8")[:15]
        libc = ctypes.CDLL("libc.so.6")
        libc.prctl.argtypes = [ctypes.c_int, ctypes.c_char_p]
        libc.prctl.restype = ctypes.c_int
        libc.prctl(15, name)
    except Exception:  # noqa: BLE001, S110
        pass


_original_thread_run = threading.Thread.run


def _patched_thread_run(self: threading.Thread) -> None:
    try:
        _set_os_thread_name()
    except Exception:  # noqa: BLE001, S110
        pass
    _original_thread_run(self)


threading.Thread.run = _patched_thread_run

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s [%(levelname)s] %(message)s",
)

from app.infrastructure.bootstrap import build_application


def main():
    """Запуск LGTU контроллера."""
    print("Запуск LGTU контроллера...")
    
    # Определить путь к конфигурации
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(script_dir, "app", "config.yml")
    
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
    except Exception as e:  # noqa: BLE001
        print(f"Ошибка работы контроллера: {e}")
        application.shutdown()
        sys.exit(1)


if __name__ == "__main__":
    main()
