#!/usr/bin/env python3
"""
Шаг 1. Получить первичный сертификат с KMS /bootstrap.

Переменные окружения:
    KMS_URL   - адрес KMS (по умолчанию https://kms-scud-dev.admlr.lipetsk.ru)
    OUT_DIR   - куда сохранить файлы (по умолчанию ./certs)

Сохраняет:
    certs/primary_cert.pem
    certs/primary_key.pem
    certs/ca.pem
"""
from __future__ import annotations

import json
import os

import requests

KMS_URL = os.environ.get("KMS_URL", "https://kms-scud-dev.admlr.lipetsk.ru").rstrip("/")
OUT_DIR = os.environ.get("OUT_DIR", os.path.join(os.path.dirname(__file__), "certs"))


def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)

    session = requests.Session()
    session.trust_env = False  # не использовать системный proxy

    url = f"{KMS_URL}/bootstrap"
    print(f"GET {url}")
    response = session.get(url, headers={"Accept": "application/json"}, timeout=10)
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
