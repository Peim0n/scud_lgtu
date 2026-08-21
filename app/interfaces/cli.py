#!/usr/bin/env python3
"""
CLI управления СКУД (см. ARCHITECTURE.md, слой Interfaces).

Две независимые группы команд:

- ``cert ...`` — управление mTLS-сертификатом контроллера. НЕ поднимает
  GPIO/ScudEngine (см. ``build_backend_client``) — безопасно запускать
  параллельно с уже работающим ``run_lgtu_controller.py`` на том же
  устройстве, конфликта за GPIO-пины не будет. Логика каждой команды
  вынесена в отдельную функцию ``cmd_*``, которая принимает простые
  аргументы и возвращает dict — этим же способом в будущем можно
  переиспользовать её для веб-интерфейса администрирования (например,
  отдать результат ``cmd_cert_status()`` как JSON через HTTP-эндпоинт), не
  дублируя логику между CLI и веб-слоем.
- ``engine ...`` — интерактивное управление СОБСТВЕННЫМ экземпляром движка
  СКУД для разработки/отладки на стенде. Поднимает GPIO — НЕ запускать
  одновременно с systemd-сервисом ``run_lgtu_controller.py`` на одном
  устройстве (конфликт за пины).

Использование:
    python -m app.interfaces.cli cert status
    python -m app.interfaces.cli cert import-initial <cert.pem> <key.pem>
    python -m app.interfaces.cli cert bootstrap
    python -m app.interfaces.cli cert rotate [--force]
    python -m app.interfaces.cli engine --interactive
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from app.application.commands import ScudCommand
from app.infrastructure.bootstrap import build_application, build_backend_client

# ---------------------------------------------------------------------------
# cert: управление mTLS-сертификатом контроллера (без GPIO)
# ---------------------------------------------------------------------------

_NOT_CONFIGURED_ERROR = (
    "CertificateManager не сконфигурирован (нет backend.cert в config.yml "
    "или недоступен модуль cryptography)"
)


def cmd_cert_status(config_path: str | None) -> dict[str, Any]:
    """Текущее состояние рабочего сертификата (не дёргает бэкенд/KMS)."""
    _backend, cert_manager = build_backend_client(config_path, ensure_bootstrap=False)
    if cert_manager is None:
        return {"error": _NOT_CONFIGURED_ERROR}
    return cert_manager.get_status()


def cmd_cert_import_initial(config_path: str | None, cert_file: str, key_file: str) -> dict[str, Any]:
    """Вручную задать первичный сертификат/ключ — альтернатива KMS."""
    _backend, cert_manager = build_backend_client(config_path, ensure_bootstrap=False)
    if cert_manager is None:
        return {"error": _NOT_CONFIGURED_ERROR}

    try:
        with open(cert_file, "r", encoding="utf-8") as f:
            cert_pem = f.read()
        with open(key_file, "r", encoding="utf-8") as f:
            key_pem = f.read()
    except OSError as exc:
        return {"error": f"не удалось прочитать файл: {exc}"}

    try:
        cert_manager.import_initial_certificate(cert_pem, key_pem)
    except ValueError as exc:
        return {"error": str(exc)}

    return {"status": "ok", "message": "Первичный сертификат импортирован, готов к 'cert bootstrap'"}


def cmd_cert_bootstrap(config_path: str | None) -> dict[str, Any]:
    """Выполнить первичный обмен (через KMS или ранее импортированный первичный сертификат)."""
    _backend, cert_manager = build_backend_client(config_path, ensure_bootstrap=False)
    if cert_manager is None:
        return {"error": _NOT_CONFIGURED_ERROR}
    cert_manager.ensure_bootstrapped()
    return cert_manager.get_status()


def cmd_cert_rotate(config_path: str | None, force: bool) -> dict[str, Any]:
    """Попробовать обменять рабочий сертификат (--force — игнорируя порог/троттлинг)."""
    _backend, cert_manager = build_backend_client(config_path, ensure_bootstrap=False)
    if cert_manager is None:
        return {"error": _NOT_CONFIGURED_ERROR}
    if not cert_manager.has_working_certificate:
        return {"error": "нет рабочего сертификата — сначала выполните 'cert bootstrap'"}

    rotated = cert_manager.force_rotate() if force else cert_manager.maybe_rotate()
    result = cert_manager.get_status()
    result["rotated"] = rotated
    return result


def _print_cert_result(result: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return
    if "error" in result:
        print(f"Ошибка: {result['error']}")
        return
    for key, value in result.items():
        print(f"{key}: {value}")


def _run_cert_command(args: argparse.Namespace) -> int:
    if args.cert_command == "status":
        result = cmd_cert_status(args.config)
    elif args.cert_command == "import-initial":
        result = cmd_cert_import_initial(args.config, args.cert_file, args.key_file)
    elif args.cert_command == "bootstrap":
        result = cmd_cert_bootstrap(args.config)
    elif args.cert_command == "rotate":
        result = cmd_cert_rotate(args.config, args.force)
    else:  # pragma: no cover - argparse с required=True сюда не пускает
        raise AssertionError(f"неизвестная cert-команда: {args.cert_command}")

    _print_cert_result(result, args.json)
    return 1 if "error" in result else 0


# ---------------------------------------------------------------------------
# engine: интерактивное управление собственным экземпляром движка (стенд/dev)
# ---------------------------------------------------------------------------


class ScudCLI:
    """Интерактивный CLI для управления СКУД.

    ВНИМАНИЕ: поднимает полный ``LGTUApplication`` (GPIO/ScudEngine) —
    только для разработки/отладки на отдельном стенде, не запускать
    одновременно с боевым ``run_lgtu_controller.py``.
    """

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
            print("2. Открыть турникет")
            print("3. Записать shift")
            print("4. Админ-команды")
            print("5. Выход")

            choice = input("Выберите действие: ").strip()

            if choice == "1":
                self.check_health()
            elif choice == "2":
                self.send_command("output", "set_output", {"output_id": 0, "duration": 1.5})
            elif choice == "3":
                value = int(input("Введите значение shift: ").strip())
                self.send_command("shift", "write_shift", {"value": value})
            elif choice == "4":
                self._admin_menu()
            elif choice == "5":
                print("Выход...")
                break
            else:
                print("❌ Неверный выбор")


def _run_engine_command(args: argparse.Namespace) -> int:
    cli = ScudCLI(args.config or "config.yml")

    if args.start:
        cli.start_engine()
    if args.interactive:
        cli.interactive_menu()
    elif args.health:
        cli.check_health()
    if args.stop:
        cli.stop_engine()
    return 0


# ---------------------------------------------------------------------------
# Точка входа
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="CLI управления СКУД")
    parser.add_argument("--config", help="Путь к config.yml")
    parser.add_argument("--json", action="store_true", help="Вывод cert-команд в формате JSON")
    subparsers = parser.add_subparsers(dest="command", required=True)

    cert_parser = subparsers.add_parser(
        "cert", help="Управление mTLS-сертификатом контроллера (без GPIO, безопасно вместе с run_lgtu_controller.py)",
    )
    cert_sub = cert_parser.add_subparsers(dest="cert_command", required=True)

    cert_sub.add_parser("status", help="Показать текущее состояние рабочего сертификата")

    import_parser = cert_sub.add_parser(
        "import-initial", help="Вручную задать первичный сертификат/ключ (вместо KMS)",
    )
    import_parser.add_argument("cert_file", help="Путь к PEM-файлу сертификата")
    import_parser.add_argument("key_file", help="Путь к PEM-файлу приватного ключа")

    cert_sub.add_parser(
        "bootstrap", help="Выполнить первичный обмен (KMS или ранее импортированный первичный сертификат)",
    )

    rotate_parser = cert_sub.add_parser("rotate", help="Попробовать ротацию рабочего сертификата")
    rotate_parser.add_argument(
        "--force", action="store_true", help="Не учитывать порог/троттлинг — обменять прямо сейчас",
    )

    engine_parser = subparsers.add_parser(
        "engine", help="Интерактивное управление движком СКУД для разработки (поднимает GPIO!)",
    )
    engine_parser.add_argument("--start", action="store_true", help="Запустить движок")
    engine_parser.add_argument("--interactive", action="store_true", help="Запустить интерактивное меню")
    engine_parser.add_argument("--health", action="store_true", help="Проверить состояние")
    engine_parser.add_argument("--stop", action="store_true", help="Остановить движок")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "cert":
        return _run_cert_command(args)
    if args.command == "engine":
        return _run_engine_command(args)
    parser.error(f"неизвестная команда: {args.command}")  # pragma: no cover
    return 2  # pragma: no cover


if __name__ == "__main__":
    sys.exit(main())
