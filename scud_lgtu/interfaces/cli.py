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
from scud_lgtu.infrastructure.bootstrap import build_application
from scud_lgtu.application.commands import ScudCommand


class ScudCLI:
    """Интерактивный CLI для управления СКУД."""

    def __init__(self, config_path: str = "config.yml"):
        """Инициализировать CLI с конфигурацией."""
        self.config_path = config_path
        self.application = None

    def start_engine(self) -> None:
        """Запустить движок СКУД."""
        print("Запуск движка СКУД...")
        self.application = build_application(self.config_path)
        self.application.start()
        print("✓ Движок запущен")

    def stop_engine(self) -> None:
        """Остановить движок СКУД."""
        if self.application:
            print("Остановка движка СКУД...")
            self.application.shutdown()
            print("✓ Движок остановлен")

    def check_health(self) -> None:
        """Проверить состояние системы."""
        if not self.application:
            print("❌ Движок не запущен")
            return

        healthy = self.application.is_healthy()
        print(f"Состояние системы: {'✓ Здоров' if healthy else '❌ Нездоров'}")

    def generate_qr(self, key_id: int, timestamp: int, max_id: int) -> None:
        """Сгенерировать тестовый QR код."""
        print(f"Генерация QR: key_id={key_id}, timestamp={timestamp}, max_id={max_id}")
        # qr_url = encode_qr(key_id, timestamp, max_id, private_key, shared_key)
        # print(f"QR URL: {qr_url}")

    def send_command(self, target: str, action: str, payload: dict) -> None:
        """Отправить команду в систему."""
        if not self.application:
            print("❌ Движок не запущен")
            return

        cmd = ScudCommand(
            target=target,
            action=action,
            payload=payload,
        )
        self.application.send_command(cmd)
        print(f"✓ Команда отправлена: {target}.{action}")

    def send_admin_command(self, command: str) -> None:
        """Отправить админ-команду в доменную логику."""
        if not self.application:
            print("❌ Движок не запущен")
            return

        self.application.send_admin_command(command)
        print(f"✓ Админ-команда отправлена: {command}")

    def _admin_menu(self) -> None:
        """Подменю админ-команд турникета."""
        while True:
            print("\n--- Админ-команды ---")
            print("1. Заблокировать (lock)")
            print("2. Разблокировать (unlock)")
            print("3. Разблокировать на вход (unlock_entry)")
            print("4. Разблокировать на выход (unlock_exit)")
            print("5. Снять разблокировку (cancel_unlock)")
            print("6. Назад")

            choice = input("Выберите действие: ").strip()
            commands = {
                "1": "lock",
                "2": "unlock",
                "3": "unlock_entry",
                "4": "unlock_exit",
                "5": "cancel_unlock",
            }
            if choice == "6":
                break
            if choice in commands:
                self.send_admin_command(commands[choice])
            else:
                print("❌ Неверный выбор")

    def interactive_menu(self) -> None:
        """Запустить интерактивное меню."""
        while True:
            print("\n=== SCUD CLI ===")
            print("1. Проверить состояние")
            print("2. Сгенерировать QR")
            print("3. Открыть турникет")
            print("4. Записать shift")
            print("5. Админ-команды")
            print("6. Выход")

            choice = input("Выберите действие: ").strip()

            if choice == "1":
                self.check_health()
            elif choice == "2":
                key_id = int(input("Введите key_id: ").strip())
                timestamp = int(input("Введите timestamp: ").strip())
                max_id = int(input("Введите max_id: ").strip())
                self.generate_qr(key_id, timestamp, max_id)
            elif choice == "3":
                self.send_command("output", "set_output", {"output_id": 0, "duration": 1.5})
            elif choice == "4":
                value = int(input("Введите значение shift: ").strip())
                self.send_command("shift", "write_shift", {"value": value})
            elif choice == "5":
                self._admin_menu()
            elif choice == "6":
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
