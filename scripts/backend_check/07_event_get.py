#!/usr/bin/env python3
"""
Шаг 7. Проверить получение последнего события через
POST controller/v1/event/get (формат ТЗ, §6.5).

Запрашивает event_id/stime/ftime последнего принятого бэкендом события.

Переменные окружения:
    CONTROLLER_URL - адрес controller (по умолчанию https://195.34.235.89:8448)
    OUT_DIR        - где лежат рабочие сертификаты / куда сохранять ответы (по умолчанию ./certs)

Сохраняет:
    certs/event_get_response.json
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

    url = f"{CONTROLLER_URL}{API_PREFIX}/event/get"
    print(f"POST {url}")
    print(f"Тело: null (нет параметров)")
    response = session.post(
        url,
        data=b"null",
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

    out_path = os.path.join(OUT_DIR, "event_get_response.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"Сохранено: {out_path}")

    # Проверка по ТЗ
    if data.get("status") == "ok":
        event_id = data.get("event_id", 0)
        stime = data.get("stime", "—")
        ftime = data.get("ftime", "—")
        print(f"\nСводка: status=ok, event_id={event_id}, stime={stime}, ftime={ftime}")
        if event_id == 0:
            print("  (событий ещё не было — контроллер только зарегистрирован)")
        return 0
    else:
        desc = data.get("description", "<без описания>")
        print(f"\nСводка: ошибка — {desc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
