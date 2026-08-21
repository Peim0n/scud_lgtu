#!/usr/bin/env python3
"""
Шаг 1. Получить первичный сертификат с KMS /bootstrap.

Переменные окружения:
    KMS_URL          - адрес KMS (по умолчанию https://kms-scud-dev.admlr.lipetsk.ru)
    ACCESS_POINT_ID  - обязательный query-параметр access_point_id (по умолчанию 2, тестовый контроллер)
    OUT_DIR          - куда сохранить файлы (по умолчанию ./certs)

ВАЖНО: WAF на KMS блокирует запросы с "ботовским" User-Agent (дефолтный
"python-requests/x.y") — 403 Forbidden от nginx ещё до приложения. С 21.08
наш IP также временно добавлен в allowlist на фаерволе (213.129.118.19,
195.98.93.98), поэтому сейчас доступ есть в любом случае — но раз
разблокировка по IP временная (allowlist могут снять), User-Agent всё равно
подставляем явно — тот же, что настроен в app/config.yml (backend.user_agent,
см. scripts/backend_check/_config.py), чтобы диагностика проверяла именно то,
с чем реально столкнётся приложение на WAF. Прокси (другой исходящий IP) не
входит в allowlist, поэтому запросы к KMS всегда идут напрямую (trust_env=False).

Сохраняет:
    certs/primary_cert.pem
    certs/primary_key.pem
    certs/ca.pem
"""
from __future__ import annotations

import json
import os

import requests

from _config import DEFAULT_ACCESS_POINT_ID, USER_AGENT

KMS_URL = os.environ.get("KMS_URL", "https://kms-scud-dev.admlr.lipetsk.ru").rstrip("/")
ACCESS_POINT_ID = os.environ.get("ACCESS_POINT_ID", DEFAULT_ACCESS_POINT_ID)
OUT_DIR = os.environ.get("OUT_DIR", os.path.join(os.path.dirname(__file__), "certs"))


def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)

    session = requests.Session()
    session.trust_env = False  # не использовать системный proxy (не входит в allowlist KMS)

    url = f"{KMS_URL}/bootstrap"
    print(f"GET {url}?access_point_id={ACCESS_POINT_ID}")
    response = session.get(
        url,
        params={"access_point_id": ACCESS_POINT_ID},
        headers={"Accept": "application/json", "User-Agent": USER_AGENT},
        timeout=10,
    )
    response.raise_for_status()

    data = response.json()
    bootstrap = data["bootstrap"]
    ca = data["ca"]

    cert_path = os.path.join(OUT_DIR, "primary_cert.pem")
    key_path = os.path.join(OUT_DIR, "primary_key.pem")
    ca_path = os.path.join(OUT_DIR, "ca.pem")

    with open(cert_path, "w", encoding="utf-8") as f:
        f.write(bootstrap["crt"])
    with open(key_path, "w", encoding="utf-8") as f:
        f.write(bootstrap["private_key"])
    os.chmod(key_path, 0o600)
    with open(ca_path, "w", encoding="utf-8") as f:
        f.write(ca["crt"])

    print(f"OK: сохранено {cert_path}, {key_path}, {ca_path}")
    print(f"primary_cert subject: {bootstrap.get('subject', 'n/a')}")


if __name__ == "__main__":
    main()
