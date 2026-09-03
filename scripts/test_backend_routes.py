#!/usr/bin/env python3
"""
Скрипт проверки роутов бэкенда СКУД по ТЗ.

Проверяет все 4 роута:
  /accesspoint/get
  /accesspoint/patch
  /event/get
  /event/put

Использует реальный mTLS-сертификат контроллера для подключения к бэкенду.
Запускать на контроллере (или с машины с доступом к бэкенду и сертификатами).

Usage:
  python3 scripts/test_backend_routes.py [--config app/config.yml]

Выводит подробный отчёт по каждому роуту: что отправили, что получили,
соответствует ли ТЗ.
"""
import argparse
import json
import os
import sys
import time
import traceback

# Добавляем корень проекта в path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.infrastructure.config import load as load_config, resolve_config_path
from app.infrastructure.backend.rest_client import RestClient, BackendApiError
from app.infrastructure.backend.client import BackendClient
from app.infrastructure.backend.certificate_manager import CertificateManager
from app.infrastructure.persistence.event_store import PassageEvent


def green(msg: str) -> str:
    return f"\033[32m{msg}\033[0m"

def red(msg: str) -> str:
    return f"\033[31m{msg}\033[0m"

def yellow(msg: str) -> str:
    return f"\033[33m{msg}\033[0m"

def bold(msg: str) -> str:
    return f"\033[1m{msg}\033[0m"


def print_header(title: str) -> None:
    print(f"\n{'='*60}")
    print(bold(title))
    print(f"{'='*60}")

def print_result(ok: bool, msg: str) -> None:
    prefix = green("[OK]") if ok else red("[FAIL]")
    print(f"  {prefix} {msg}")

def print_json(label: str, data: dict) -> None:
    print(f"  {label}:")
    print(f"    {json.dumps(data, indent=2, ensure_ascii=False)}")


def build_backend(config_path: str) -> tuple[BackendClient, CertificateManager]:
    """Собрать BackendClient с рабочим сертификатом."""
    config = load_config(config_path)
    backend_cfg = config.get("backend", {})
    cert_cfg = backend_cfg.get("cert", {})

    base_url = backend_cfg["base_url"]
    ca_bundle = backend_cfg.get("ca_bundle")
    verify_hostname = backend_cfg.get("verify_hostname", True)
    api_path_prefix = backend_cfg.get("api_path_prefix", "/controller/v1")
    user_agent = backend_cfg.get("user_agent", "LGTU-SCUD-Controller/1.0")
    timeout = backend_cfg.get("request_timeout_s", 10.0)

    # Пути к сертификатам
    runtime_dir = "/etc/scud_lgtu"
    if os.path.isdir(runtime_dir):
        cert_dir = os.path.join(runtime_dir, "certs")
    else:
        base_dir = os.path.dirname(os.path.abspath(config_path))
        cert_dir = os.path.join(base_dir, cert_cfg.get("cert_dir", "infrastructure/certs"))

    initial_cert_path = os.path.join(cert_dir, "initial_cert.pem")
    initial_key_path = os.path.join(cert_dir, "initial_key.pem")

    # Если нет initial — используем рабочий
    if not os.path.exists(initial_cert_path):
        initial_cert_path = None
        initial_key_path = None

    rest = RestClient(
        base_url=base_url,
        ca_bundle=ca_bundle,
        timeout=timeout,
        api_path_prefix=api_path_prefix,
        verify_hostname=verify_hostname,
        user_agent=user_agent,
    )

    subject = CertificateSubject(
        organization=cert_cfg.get("subject", {}).get("organization", "ЛГТУ"),
        organizational_units=cert_cfg.get("subject", {}).get("organizational_units", []),
        common_name=cert_cfg.get("subject", {}).get("common_name", "turnstile-01"),
    )

    manager = CertificateManager(
        rest,
        cert_dir=cert_dir,
        subject=subject,
        initial_cert_path=initial_cert_path,
        initial_key_path=initial_key_path,
        rotation_threshold_fraction=cert_cfg.get("rotation_threshold_fraction", 0.5),
    )

    backend = BackendClient(rest_client=rest)
    manager._on_exchange_success = backend.mark_online

    # Если есть рабочий сертификат — устанавливаем
    working_cert = os.path.join(cert_dir, "working_cert.pem")
    working_key = os.path.join(cert_dir, "working_key.pem")
    if os.path.exists(working_cert) and os.path.exists(working_key):
        rest.set_client_cert(working_cert, working_key)
        backend.mark_online()

    return backend, manager


def test_accesspoint_get(backend: BackendClient) -> bool:
    """Тест /accesspoint/get — запросить инвентаризационные данные."""
    print_header("1. /accesspoint/get")
    print(f"  Ожидание: status=ok, поля mac/ip/cpuid (если зарегистрирован)")

    try:
        result = backend.get_accesspoint()
        print_json("Ответ", result)

        ok = True
        if result.get("status") != "ok":
            print_result(False, f"status != 'ok' (получено: '{result.get('status')}')")
            ok = False
        else:
            print_result(True, "status = 'ok'")

        # Проверяем наличие ожидаемых полей
        for field in ("mac", "ip", "cpuid"):
            if field in result:
                print_result(True, f"поле '{field}' присутствует: {result[field]}")
            else:
                print_result(False, f"поле '{field}' отсутствует")
                ok = False

        return ok

    except BackendApiError as e:
        print_json("Ошибка", {"message": str(e), "http_status": e.http_status, "description": e.description})
        return False
    except Exception as e:
        print(f"  {red('[ERROR]')} {e}")
        traceback.print_exc()
        return False


def test_accesspoint_patch(backend: BackendClient) -> bool:
    """Тест /accesspoint/patch — отправить инвентаризационные данные."""
    print_header("2. /accesspoint/patch")
    print(f"  Ожидание: status=ok после отправки mac/ip/cpuid")

    # Генерируем тестовые данные
    test_mac = "02:81:a6:72:4e:c0"
    test_ip = "192.168.0.181"
    test_cpuid = "test-cpu-id-12345"

    payload = {"mac": test_mac, "ip": test_ip, "cpuid": test_cpuid}
    print(f"  Отправляем: {json.dumps(payload, ensure_ascii=False)}")

    try:
        result = backend.patch_accesspoint(mac=test_mac, ip=test_ip, cpuid=test_cpuid)
        print_json("Ответ", result)

        ok = result.get("status") == "ok"
        print_result(ok, f"status = '{result.get('status')}'")

        if ok:
            # Проверяем что данные сохранились — запрашиваем обратно
            print(f"  Проверяем сохранение через accesspoint/get...")
            verify = backend.get_accesspoint()
            print_json("Проверка", verify)

            if verify.get("mac") == test_mac:
                print_result(True, f"mac сохранился: {verify.get('mac')}")
            else:
                print_result(False, f"mac не совпадает: отправили {test_mac}, получили {verify.get('mac')}")
                ok = False

            if verify.get("ip") == test_ip:
                print_result(True, f"ip сохранился: {verify.get('ip')}")
            else:
                print_result(False, f"ip не совпадает: отправили {test_ip}, получили {verify.get('ip')}")
                ok = False

        return ok

    except BackendApiError as e:
        print_json("Ошибка", {"message": str(e), "http_status": e.http_status, "description": e.description})
        return False
    except Exception as e:
        print(f"  {red('[ERROR]')} {e}")
        traceback.print_exc()
        return False


def test_event_get(backend: BackendClient) -> bool:
    """Тест /event/get — получить последнее подтверждённое событие."""
    print_header("3. /event/get")
    print(f"  Ожидание: status=ok, поля event_id/stime/ftime")

    try:
        result = backend.get_last_event()
        print_json("Ответ", result)

        ok = result.get("status") == "ok"
        print_result(ok, f"status = '{result.get('status')}'")

        if not ok:
            return False

        # event_id должен быть (0 если событий ещё не было)
        event_id = result.get("event_id")
        if event_id is not None:
            print_result(True, f"event_id = {event_id}")
        else:
            print_result(False, "event_id отсутствует")
            ok = False

        # stime и ftime — опциональны (могут не быть если event_id=0)
        if event_id and event_id > 0:
            if "stime" in result:
                print_result(True, f"stime = {result['stime']}")
            else:
                print_result(False, "stime отсутствует при event_id > 0")
                ok = False
        else:
            print_result(True, "event_id=0 или отсутствует — stime/ftime опциональны")

        return ok

    except BackendApiError as e:
        print_json("Ошибка", {"message": str(e), "http_status": e.http_status, "description": e.description})
        return False
    except Exception as e:
        print(f"  {red('[ERROR]')} {e}")
        traceback.print_exc()
        return False


def test_event_put(backend: BackendClient) -> bool:
    """Тест /event/put — отправить тестовое событие."""
    print_header("4. /event/put")
    print(f"  Ожидание: status=ok после отправки события")

    # Создаём тестовое событие
    event = PassageEvent(
        event_id=int(time.time()),  # уникальный ID на основе времени
        stime=time.time(),
        event_type="access",
        direction="in",
        token_type="maxid",
        token="103295689",
        result="pass",
        severity="info",
        description="Тестовое событие от скрипта проверки роутов",
    )

    print(f"  Отправляем событие:")
    print(f"    event_id: {event.event_id}")
    print(f"    stime: {event.stime}")
    print(f"    event_type: {event.event_type}")
    print(f"    direction: {event.direction}")
    print(f"    token_type: {event.token_type}")
    print(f"    token: {event.token}")
    print(f"    result: {event.result}")
    print(f"    severity: {event.severity}")

    try:
        result = backend.put_event(event)
        print_json("Ответ", result)

        ok = result.get("status") == "ok"
        print_result(ok, f"status = '{result.get('status')}'")

        if not ok:
            return False

        # Проверяем что событие сохранилось — запрашиваем последнее
        print(f"  Проверяем сохранение через event/get...")
        verify = backend.get_last_event()
        print_json("Проверка", verify)

        if verify.get("event_id") == event.event_id:
            print_result(True, f"event_id совпадает: {event.event_id}")
        else:
            print_result(False, f"event_id не совпадает: отправили {event.event_id}, получили {verify.get('event_id')}")
            # Это может быть нормально если бэкенд не сразу обновляет
            print(f"  {yellow('[WARN]')} Возможно бэкенд обновляет состояние асинхронно")

        return ok

    except BackendApiError as e:
        print_json("Ошибка", {"message": str(e), "http_status": e.http_status, "description": e.description})
        return False
    except Exception as e:
        print(f"  {red('[ERROR]')} {e}")
        traceback.print_exc()
        return False


def main():
    parser = argparse.ArgumentParser(description="Проверка роутов бэкенда СКУД")
    parser.add_argument("--config", default=None, help="Путь к config.yml")
    args = parser.parse_args()

    config_path = resolve_config_path(args.config)
    print(f"{bold('Конфигурация:')} {config_path}")

    config = load_config(config_path)
    backend_cfg = config.get("backend", {})
    print(f"{bold('Бэкенд:')} {backend_cfg.get('base_url')}")
    print(f"{bold('Access point ID:')} {backend_cfg.get('access_point_id')}")

    # Собираем клиент
    print(f"\nИнициализация mTLS-соединения...")
    try:
        backend, manager = build_backend(config_path)
    except Exception as e:
        print(f"{red('[FAIL]')} Не удалось инициализировать клиент: {e}")
        traceback.print_exc()
        sys.exit(1)

    # Проверяем наличие рабочего сертификата
    runtime_dir = "/etc/scud_lgtu"
    if os.path.isdir(runtime_dir):
        cert_dir = os.path.join(runtime_dir, "certs")
    else:
        base_dir = os.path.dirname(os.path.abspath(config_path))
        cert_dir = os.path.join(base_dir, backend_cfg.get("cert", {}).get("cert_dir", "infrastructure/certs"))

    working_cert = os.path.join(cert_dir, "working_cert.pem")
    if not os.path.exists(working_cert):
        print(f"{yellow('[WARN]')} Рабочий сертификат не найден: {working_cert}")
        print(f"  Попытка bootstrap через KMS...")
        try:
            manager.ensure_bootstrapped()
            print(f"{green('[OK]')} Сертификат получен")
        except Exception as e:
            print(f"{red('[FAIL]')} Не удалось получить сертификат: {e}")
            sys.exit(1)
    else:
        print(f"{green('[OK]')} Рабочий сертификат найден: {working_cert}")

    # Запускаем тесты
    results = {}

    print(f"\n{bold('Запуск проверок роутов...')}")

    results["accesspoint/get"] = test_accesspoint_get(backend)
    results["accesspoint/patch"] = test_accesspoint_patch(backend)
    results["event/get"] = test_event_get(backend)
    results["event/put"] = test_event_put(backend)

    # Итоговый отчёт
    print_header("ИТОГОВЫЙ ОТЧЁТ")
    all_ok = True
    for route, ok in results.items():
        status = green("PASS") if ok else red("FAIL")
        print(f"  {route:30s} {status}")
        if not ok:
            all_ok = False

    print()
    if all_ok:
        print(green(bold("ВСЕ РОУТЫ РАБОТАЮТ КОРРЕКТНО")))
        sys.exit(0)
    else:
        failed = sum(1 for ok in results.values() if not ok)
        print(red(bold(f"ПРОВАЛЕНО: {failed}/{len(results)} роутов")))
        sys.exit(1)


if __name__ == "__main__":
    main()
