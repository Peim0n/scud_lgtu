#!/usr/bin/env python3
"""
Шаг 4. Проверить получение списка идентификаторов доступа через
POST controller/v1/access/get (формат ТЗ, тело {"update": ...}, §5.4.3/§6.5).

Использует рабочий сертификат, полученный на шаге 2.

По умолчанию делает оба запроса подряд:
    1. update=0 — принудительно полный список (как при первом запуске контроллера).
    2. update=1 — только изменения с прошлого запроса (обычно пусто сразу после
       полного обновления, но так проверяется сама ветка "нет изменений").

Переменные окружения:
    CONTROLLER_URL - адрес controller (по умолчанию https://195.34.235.89:8448)
    OUT_DIR        - где лежат рабочие сертификаты / куда сохранять ответы (по умолчанию ./certs)
    UPDATE         - если задан явно (0 или 1), делается только один запрос с этим значением;
                     если не задан — выполняются оба запроса по очереди (0, затем 1)

Сохраняет:
    certs/access_response_update0.json
    certs/access_response_update1.json
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
# Если UPDATE не задан явно в окружении — проверяем оба режима (0 и 1) по очереди.
_UPDATE_ENV = os.environ.get("UPDATE")
UPDATE_VALUES = [int(_UPDATE_ENV)] if _UPDATE_ENV is not None else [0, 1]


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
    # Для теста по IP отключаем проверку сертификата сервера (hostname mismatch).
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    session.verify = False
    return session


def _summarize(data: dict) -> str:
    """Короткая сводка по ответу access/get (§5.4.3): счётчики id[]/users, dynamic_key."""
    if data.get("status") != "ok":
        return f"ошибка: {data.get('description', '<без описания>')}"

    parts = []
    if "id" in data:
        counts = {item.get("type", "?"): len(item.get("list", [])) for item in data["id"]}
        parts.append(f"id={counts}" if counts else "id=[] (пустой список)")
    else:
        parts.append("id отсутствует (нет изменений с прошлого запроса)")

    if "dynamic_key" in data:
        parts.append("dynamic_key=есть")

    users = data.get("users")
    if users:
        parts.append(f"users={len(users)}")

    return ", ".join(parts)


def _request_access(session: requests.Session, update: int) -> dict:
    url = f"{CONTROLLER_URL}{API_PREFIX}/access/get"
    print(f"\nPOST {url} {{'update': {update}}}")
    response = session.post(
        url,
        data=json.dumps({"update": update}).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json", "User-Agent": USER_AGENT},
        timeout=10,
    )
    print(f"HTTP {response.status_code}")

    try:
        data = response.json()
    except ValueError:
        print(f"Не-JSON тело ответа: {response.text!r}")
        raise

    print(json.dumps(data, indent=2, ensure_ascii=False))

    out_path = os.path.join(OUT_DIR, f"access_response_update{update}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"Сохранено: {out_path}")
    print(f"Сводка: {_summarize(data)}")

    return data


def main() -> int:
    session = _build_session()

    had_error = False
    for update in UPDATE_VALUES:
        try:
            data = _request_access(session, update)
        except requests.RequestException as exc:
            print(f"Сетевая ошибка при update={update}: {exc}")
            had_error = True
            continue

        if data.get("status") == "error":
            had_error = True

    return 1 if had_error else 0


if __name__ == "__main__":
    sys.exit(main())
