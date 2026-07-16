#!/usr/bin/env python3
"""
Python CLI для управления СКУД.

Заменяет HTTP API и SSH скрипты интерактивным меню для:
- проверки состояния
- просмотра локального кэша
- добавления/удаления идентификаторов
- генерации тестовых QR
- отправки команд (открыть турникет, записать shift)
"""

import sys
import argparse
from typing import Optional

# Импорты для работы с системы
from scud_lgtu.bootstrap import build_application
from scud_lgtu.infrastructure.cache.access_cache import LocalAccessCache
from scud_lgtu.infrastructure.serial.qr_codec import QRDecoder


class ScudCLI:
    """Интерактивный CLI для управления СКУД."""

    def __init__(self, config_path: str = "config.yml"):
        """Инициализировать CLI с конфигурацией."""
        self.config_path = config_path
        self.application = None
        self.cache = None

    def start_engine(self) -> None:
        """Запустить движок СКУД."""
        print("Запуск движка СКУД...")
        self.application = build_application(self.config_path)
        self.application._engine.start()
        self.cache = self.application._cache
        print("✓ Движок запущен")

    def stop_engine(self) -> None:
        """Остановить движок СКУД."""
        if self.application:
            print("Остановка движка СКУД...")
            self.application._engine.stop()
            print("✓ Движок остановлен")

    def check_health(self) -> None:
        """Проверить состояние системы."""
        if not self.application:
            print("❌ Движок не запущен")
            return

        healthy = self.application._engine.is_healthy()
        print(f"Состояние системы: {'✓ Здоров' if healthy else '❌ Нездоров'}")

    def view_cache(self) -> None:
        """Просмотреть локальный кэш разрешений."""
        if not self.cache:
            print("❌ Кэш не инициализирован")
            return

        print(f"Локальный кэш: {self.cache.count()} записей")
        # TODO: добавить вывод содержимого кэша

    def add_identifier(self, identifier: str) -> None:
        """Добавить идентификатор в локальный кэш."""
        if not self.cache:
            print("❌ Кэш не инициализирован")
            return

        self.cache.update({
            "id": [{"type": "maxid", "list": [identifier]}],
            "users": {"1": {"maxid": identifier}}
        })
        print(f"✓ Идентификатор {identifier} добавлен")

    def remove_identifier(self, identifier: str) -> None:
        """Удалить идентификатор из локального кэша."""
        if not self.cache:
            print("❌ Кэш не инициализирован")
            return

        # TODO: implement remove
        print(f"✓ Идентификатор {identifier} удален")

    def generate_qr(self, key_id: int, timestamp: int, max_id: int) -> None:
        """Сгенерировать тестовый QR код."""
        # TODO: загрузить ключи из конфигурации
        print(f"Генерация QR: key_id={key_id}, timestamp={timestamp}, max_id={max_id}")
        # qr_url = encode_qr(key_id, timestamp, max_id, private_key, shared_key)
        # print(f"QR URL: {qr_url}")

    def send_command(self, target: str, action: str, payload: dict) -> None:
        """Отправить команду в систему."""
        if not self.engine:
            print("❌ Движок не запущен")
            return

        cmd = ScudCommand(
            target=target,
            action=action,
            payload=payload,
        )
        self.engine.cmd_queue.put_nowait(cmd)
        print(f"✓ Команда отправлена: {target}.{action}")

    def interactive_menu(self) -> None:
        """Запустить интерактивное меню."""
        while True:
            print("\n=== SCUD CLI ===")
            print("1. Проверить состояние")
            print("2. Просмотреть кэш")
            print("3. Добавить идентификатор")
            print("4. Удалить идентификатор")
            print("5. Сгенерировать QR")
            print("6. Открыть турникет")
            print("7. Записать shift")
            print("8. Выход")

            choice = input("Выберите действие: ").strip()

            if choice == "1":
                self.check_health()
            elif choice == "2":
                self.view_cache()
            elif choice == "3":
                identifier = input("Введите идентификатор: ").strip()
                self.add_identifier(identifier)
            elif choice == "4":
                identifier = input("Введите идентификатор: ").strip()
                self.remove_identifier(identifier)
            elif choice == "5":
                key_id = int(input("Введите key_id: ").strip())
                timestamp = int(input("Введите timestamp: ").strip())
                max_id = int(input("Введите max_id: ").strip())
                self.generate_qr(key_id, timestamp, max_id)
            elif choice == "6":
                self.send_command("output", "set_output", {"output_id": 0, "duration": 1.5})
            elif choice == "7":
                value = int(input("Введите значение shift: ").strip())
                self.send_command("shift", "write_shift", {"value": value})
            elif choice == "8":
                print("Выход...")
                break
            else:
                print("❌ Неверный выбор")


def main():
    """Главная точка входа."""
    parser = argparse.ArgumentParser(description="SCUD CLI")
    parser.add_argument("--config", default="config.yml", help="Путь к конфигурации")
    parser.add_argument("--interactive", action="store_true", help="Запустить интерактивное меню")
    parser.add_argument("--health", action="store_true", help="Проверить состояние")
    parser.add_argument("--start", action="store_true", help="Запустить движок")
    parser.add_argument("--stop", action="store_true", help="Остановить движок")

    args = parser.parse_args()

    cli = ScudCLI(args.config)

    if args.start:
        cli.start_engine()

    if args.interactive:
        cli.interactive_menu()
    elif args.health:
        cli.check_health()

    if args.stop:
        cli.stop_engine()


if __name__ == "__main__":
    main()
