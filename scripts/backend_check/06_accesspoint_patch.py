#!/usr/bin/env python3
"""
Шаг 6. Проверить отправку инвентаризационных данных через
POST controller/v1/accesspoint/patch (формат ТЗ, §6.5).

Отправляет mac/ip/cpuid контроллера и проверяет, что бэкенд принимает.

Переменные окружения:
    CONTROLLER_URL - адрес controller (по умолчанию https://195.34.235.89:8448)
    OUT_DIR        - где лежат рабочие сертификаты / куда сохранять ответы (по умолчанию ./certs)
    MAC            - MAC-адрес (по умолчанию 02:81:a6:72:4e:c0)
    IP             - IP-адрес (по умолчанию 192.168.0.181)
    CPUID          - CPU ID (по умолчанию test-cpu-12345)

Сохраняет:
    certs/accesspoint_patch_response.json
"""
from __future__ import annotations

import json
import os
import sys

import requests
import urllib3

from _config import USER_AGENT

CONTROLLER_URL = os.environ.get("CONTROLLER_URL", "https://195.34.235.89:8448").rstrip("/")
API_PREFIX = "/controller/v1"
OUT_DIR = os.environ.get("OUT_DIR", os.path.join(os.path.dirname(__file__), "certs"))
MAC = os.environ.get("MAC", "02:81:a6:72:4e:c0")
IP = os.environ.get("IP", "192.168.0.181")
CPUID = os.environ.get("CPUID", "02c00081a6724ec0")


def _build_session() -> requests.Session:
    working_cert = os.path.join(OUT_DIR, "working_cert.pem")
    working_key = os.path.join(OUT_DIR, "working_key.pem")
    ca = os.path.join(OUT_DIR, "ca.pem")

    for path in (working_cert, working_key, ca):
        if not os.path.exists(path):
            raise FileNotFoundError(f"Не найден {path}. Сначала запустите 02_exchange_working.py")

    session = requests.Session()
    session.trust_env = False
    session.cert = (working_cert, working_key)
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    session.verify = False
    return session


def main() -> int:
    session = _build_session()

    payload = {"mac": MAC, "ip": IP, "cpuid": CPUID}
    url = f"{CONTROLLER_URL}{API_PREFIX}/accesspoint/patch"
    print(f"POST {url}")
    print(f"Тело: {json.dumps(payload, ensure_ascii=False)}")

    response = session.post(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json", "User-Agent": USER_AGENT},
        timeout=10,
    )
    print(f"HTTP {response.status_code}")

    try:
        data = response.json()
    except ValueError:
        print(f"Не-JSON тело ответа: {response.text!r}")
        return 1

    print(json.dumps(data, indent=2, ensure_ascii=False))

    out_path = os.path.join(OUT_DIR, "accesspoint_patch_response.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"Сохранено: {out_path}")

    if data.get("status") == "ok":
        print(f"\nСводка: status=ok — инвентаризация отправлена (mac={MAC}, ip={IP}, cpuid={CPUID})")

        # Проверяем что данные сохранились — запрашиваем обратно
        print(f"\nПроверка: запрашиваем accesspoint/get...")
        get_url = f"{CONTROLLER_URL}{API_PREFIX}/accesspoint/get"
        get_resp = session.post(
            get_url,
            data=b"null",
            headers={"Content-Type": "application/json", "Accept": "application/json", "User-Agent": USER_AGENT},
            timeout=10,
        )
        get_data = get_resp.json()
        print(json.dumps(get_data, indent=2, ensure_ascii=False))

        if get_data.get("mac") == MAC and get_data.get("ip") == IP:
            print(f"\nПроверка: OK — данные сохранились (mac={get_data.get('mac')}, ip={get_data.get('ip')})")
            return 0
        else:
            print(f"\nПроверка: WARN — данные не совпадают")
            print(f"  Отправили: mac={MAC}, ip={IP}")
            print(f"  Получили:  mac={get_data.get('mac')}, ip={get_data.get('ip')}")
            return 1
    else:
        desc = data.get("description", "<без описания>")
        print(f"\nСводка: ошибка — {desc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
