#!/usr/bin/env python3
"""
Шаг 3. Проверить получение ключей через controller/v1/keys/get.

Использует рабочий сертификат, полученный на шаге 2.
"""
from __future__ import annotations

import json
import os
import urllib3

import requests

CONTROLLER_URL = os.environ.get("CONTROLLER_URL", "https://195.34.235.89:8448").rstrip("/")
API_PREFIX = "/controller/v1"
OUT_DIR = os.environ.get("OUT_DIR", os.path.join(os.path.dirname(__file__), "certs"))


def main() -> None:
    working_cert = os.path.join(OUT_DIR, "working_cert.pem")
    working_key = os.path.join(OUT_DIR, "working_key.pem")
    ca = os.path.join(OUT_DIR, "ca.pem")

    for path in (working_cert, working_key, ca):
        if not os.path.exists(path):
            raise FileNotFoundError(f"Не найден {path}. Сначала запустите 02_exchange_working.py")

    session = requests.Session()
    session.trust_env = False
    session.cert = (working_cert, working_key)
    # Для теста по IP отключаем проверку сертификата сервера (hostname mismatch).
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    session.verify = False

    url = f"{CONTROLLER_URL}{API_PREFIX}/keys"
    print(f"GET {url}")
    response = session.get(
        url,
        headers={"Accept": "application/json"},
        timeout=10,
    )
    response.raise_for_status()
    print(json.dumps(response.json(), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
