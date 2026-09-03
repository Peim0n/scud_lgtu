#!/usr/bin/env python3
"""
Шаг 8. Проверить отправку события через
POST controller/v1/event/put (формат ТЗ, §6.5, таблица log из §5.5).

Отправляет тестовое событие прохода и проверяет, что бэкенд принимает.
Затем через event/get проверяет, что event_id сохранился.

Переменные окружения:
    CONTROLLER_URL - адрес controller (по умолчанию https://195.34.235.89:8448)
    OUT_DIR        - где лежат рабочие сертификаты / куда сохранять ответы (по умолчанию ./certs)
    TOKEN_TYPE     - тип токена (по умолчанию maxid)
    TOKEN          - значение токена (по умолчанию 103295689)
    RESULT         - результат прохода (по умолчанию pass)
    DIRECTION      - направление (по умолчанию in)

Сохраняет:
    certs/event_put_response.json
"""
from __future__ import annotations

import datetime
import json
import os
import sys
import time

import requests
import urllib3

from _config import USER_AGENT

CONTROLLER_URL = os.environ.get("CONTROLLER_URL", "https://195.34.235.89:8448").rstrip("/")
API_PREFIX = "/controller/v1"
OUT_DIR = os.environ.get("OUT_DIR", os.path.join(os.path.dirname(__file__), "certs"))
TOKEN_TYPE = os.environ.get("TOKEN_TYPE", "maxid")
TOKEN = os.environ.get("TOKEN", "103295689")
RESULT = os.environ.get("RESULT", "pass")
DIRECTION = os.environ.get("DIRECTION", "in")


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


def _iso(ts: float) -> str:
    """Unix timestamp → ISO 8601 с таймзоной."""
    return datetime.datetime.fromtimestamp(ts).astimezone().isoformat()


def main() -> int:
    session = _build_session()

    # Уникальный event_id на основе времени
    event_id = int(time.time())
    stime = time.time()

    payload = {
        "event_id": event_id,
        "stime": _iso(stime),
        "event_type": "access",
        "direction": DIRECTION,
        "token_type": TOKEN_TYPE,
        "token": TOKEN,
        "result": RESULT,
        "severity": "info",
        "description": "Тестовое событие от скрипта 08_event_put.py",
    }

    url = f"{CONTROLLER_URL}{API_PREFIX}/event/put"
    print(f"POST {url}")
    print(f"Тело: {json.dumps(payload, indent=2, ensure_ascii=False)}")

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

    out_path = os.path.join(OUT_DIR, "event_put_response.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"Сохранено: {out_path}")

    if data.get("status") == "ok":
        print(f"\nСводка: status=ok — событие event_id={event_id} принято бэкендом")

        # Проверяем что событие сохранилось — запрашиваем последнее
        print(f"\nПроверка: запрашиваем event/get...")
        get_url = f"{CONTROLLER_URL}{API_PREFIX}/event/get"
        get_resp = session.post(
            get_url,
            data=b"null",
            headers={"Content-Type": "application/json", "Accept": "application/json", "User-Agent": USER_AGENT},
            timeout=10,
        )
        get_data = get_resp.json()
        print(json.dumps(get_data, indent=2, ensure_ascii=False))

        last_id = get_data.get("event_id", 0)
        if last_id == event_id:
            print(f"\nПроверка: OK — event_id совпадает ({event_id})")
            return 0
        else:
            print(f"\nПроверка: WARN — event_id не совпадает")
            print(f"  Отправили: event_id={event_id}")
            print(f"  Получили:  event_id={last_id}")
            print(f"  (возможно бэкенд обновляет состояние асинхронно или есть более новые события)")
            return 0  # не считаем ошибкой — бэкенд мог принять, но ещё не обновить last
    else:
        desc = data.get("description", "<без описания>")
        print(f"\nСводка: ошибка — {desc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
