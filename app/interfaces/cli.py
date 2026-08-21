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
    python -m app.interfaces.cli settings get backend.access_point_id
    python -m app.interfaces.cli settings set backend.access_point_id 2
    python -m app.interfaces.cli settings show
    python -m app.interfaces.cli web [--host 0.0.0.0] [--port 8080]
    python -m app.interfaces.cli engine --interactive
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from typing import Any

from app.application.commands import ScudCommand
from app.infrastructure.bootstrap import build_application, build_backend_client
from app.infrastructure.config import load as load_config, resolve_config_path
from app.infrastructure.config import object_config as obj_cfg
from app.interfaces.web.server import create_app

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
# settings: редактирование объектного конфига (access/qr_decoder/backend)
# ---------------------------------------------------------------------------


def cmd_settings_get(config_path: str | None, dotted_path: str) -> dict[str, Any]:
    """Прочитать значение из объединённого конфига по dotted-пути."""
    resolved = resolve_config_path(config_path)
    if not obj_cfg.is_editable_path(dotted_path):
        return {
            "error": (
                f"путь '{dotted_path}' не относится к редактируемым "
                f"секциям (access, qr_decoder, backend, device, web)"
            ),
        }
    try:
        merged = load_config(resolved)
        value = obj_cfg.get(merged, dotted_path)
        return {"value": value}
    except KeyError:
        return {"error": f"ключ '{dotted_path}' не найден в конфигурации"}
    except Exception as exc:  # pragma: no cover - защита от неожиданных ошибок
        return {"error": str(exc)}


def cmd_settings_set(
    config_path: str | None, dotted_path: str, raw_value: str,
) -> dict[str, Any]:
    """Установить значение в object_config.yml."""
    resolved = resolve_config_path(config_path)
    if not obj_cfg.is_editable_path(dotted_path):
        return {
            "error": (
                f"путь '{dotted_path}' не относится к редактируемым "
                f"секциям (access, qr_decoder, backend, device, web)"
            ),
        }
    try:
        parsed = obj_cfg.parse_typed_value(raw_value)
        merged = load_config(resolved)
        # Запрещаем создавать новые ключи — только менять существующие
        _ = obj_cfg.get(merged, dotted_path)
        override = obj_cfg.load(resolved)
        obj_cfg.set_value(override, dotted_path, parsed)
        obj_cfg.save(override, resolved)
        return {"status": "ok", "path": dotted_path, "value": parsed}
    except KeyError:
        return {"error": f"ключ '{dotted_path}' не найден в конфигурации"}
    except ValueError as exc:
        return {"error": str(exc)}
    except Exception as exc:  # pragma: no cover
        return {"error": str(exc)}


def cmd_settings_show(config_path: str | None) -> dict[str, Any]:
    """Показать текущий объектный конфиг."""
    resolved = resolve_config_path(config_path)
    override = obj_cfg.load(resolved)
    return {"config": override}


def _print_settings_result(result: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return
    if "error" in result:
        print(f"Ошибка: {result['error']}")
        return
    if "value" in result:
        print(result["value"])
        return
    if "config" in result:
        print(json.dumps(result["config"], indent=2, ensure_ascii=False))
        return
    for key, value in result.items():
        print(f"{key}: {value}")


def _run_settings_command(args: argparse.Namespace) -> int:
    if args.settings_command == "get":
        result = cmd_settings_get(args.config, args.key)
    elif args.settings_command == "set":
        result = cmd_settings_set(args.config, args.key, args.value)
    elif args.settings_command == "show":
        result = cmd_settings_show(args.config)
    else:  # pragma: no cover
        raise AssertionError(f"неизвестная settings-команда: {args.settings_command}")

    _print_settings_result(result, args.json)
    return 1 if "error" in result else 0


# ---------------------------------------------------------------------------
# web: веб-интерфейс администрирования (без GPIO, отдельный сервис)
# ---------------------------------------------------------------------------


def cmd_web(
    config_path: str | None, host: str | None, port: int | None, debug: bool,
) -> int:
    """Запустить веб-интерфейс администрирования.

    Параметры host/port берутся из object_config.yml (секция web),
    если не переданы явно через аргументы CLI. Если web.enabled = false,
    команда завершается с сообщением.
    """
    resolved = resolve_config_path(config_path)
    cfg = load_config(resolved)
    web_cfg = cfg.get("web", {})

    if not web_cfg.get("enabled", True):
        print("Веб-интерфейс отключён (web.enabled = false).")
        print("Включите: python -m app.interfaces.cli settings set web.enabled true")
        return 1

    actual_host = host or web_cfg.get("host", "0.0.0.0")
    actual_port = port or int(web_cfg.get("port", 8080))

    logging.basicConfig(level=logging.INFO)
    app = create_app(config_path)
    app.run(host=actual_host, port=actual_port, debug=debug)
    return 0


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
    parser.add_argument("--json", action="store_true", help="Вывод в формате JSON")
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

    settings_parser = subparsers.add_parser(
        "settings", help="Редактирование объектного конфига (access, qr_decoder, backend, device, web)",
    )
    settings_sub = settings_parser.add_subparsers(dest="settings_command", required=True)

    settings_get = settings_sub.add_parser(
        "get", help="Прочитать значение по dotted-пути (например backend.access_point_id)",
    )
    settings_get.add_argument("key", help="dotted-путь внутри access/qr_decoder/backend/device/web")

    settings_set = settings_sub.add_parser(
        "set", help="Записать значение по dotted-пути в object_config.yml",
    )
    settings_set.add_argument("key", help="dotted-путь внутри access/qr_decoder/backend/device/web")
    settings_set.add_argument("value", help="новое значение (int/float/bool/null/string/JSON)")

    settings_sub.add_parser("show", help="Показать текущий объектный конфиг")

    web_parser = subparsers.add_parser(
        "web", help="Запустить веб-интерфейс администрирования (без GPIO)",
    )
    web_parser.add_argument("--host", default=None, help="Хост для прослушивания (по умолчанию из config.yml)")
    web_parser.add_argument("--port", type=int, default=None, help="Порт (по умолчанию из config.yml)")
    web_parser.add_argument("--debug", action="store_true", help="Режим отладки Flask")

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
    if args.command == "settings":
        return _run_settings_command(args)
    if args.command == "web":
        return cmd_web(args.config, args.host, args.port, args.debug)
    if args.command == "engine":
        return _run_engine_command(args)
    parser.error(f"неизвестная команда: {args.command}")  # pragma: no cover
    return 2  # pragma: no cover


if __name__ == "__main__":
    sys.exit(main())
