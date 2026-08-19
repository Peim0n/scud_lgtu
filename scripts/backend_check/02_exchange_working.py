#!/usr/bin/env python3
"""
Шаг 2. Обменять первичный сертификат на рабочий через controller/v1/cert/get.

Переменные окружения:
    CONTROLLER_URL - адрес controller (по умолчанию https://controller-skud-dev.admlr.lipetsk.ru)
    OUT_DIR        - где лежат первичные сертификаты (по умолчанию ./certs)
    CN             - Common Name для рабочего сертификата (по умолчанию turnstile-test)

Сохраняет:
    certs/working_cert.pem
    certs/working_key.pem
"""
from __future__ import annotations

import json
import os
import urllib3

import requests
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

CONTROLLER_URL = os.environ.get("CONTROLLER_URL", "https://195.34.235.89:8448").rstrip("/")
API_PREFIX = "/controller/v1"
OUT_DIR = os.environ.get("OUT_DIR", os.path.join(os.path.dirname(__file__), "certs"))
CN = os.environ.get("CN", "turnstile-test")


def load_subject_from_cert(cert_path: str) -> x509.Name:
    """Если нужно повторить Subject из первичного сертификата."""
    with open(cert_path, "rb") as f:
        cert = x509.load_pem_x509_certificate(f.read())
    return cert.subject


def main() -> None:
    primary_cert = os.path.join(OUT_DIR, "primary_cert.pem")
    primary_key = os.path.join(OUT_DIR, "primary_key.pem")
    ca = os.path.join(OUT_DIR, "ca.pem")

    for path in (primary_cert, primary_key, ca):
        if not os.path.exists(path):
            raise FileNotFoundError(f"Не найден {path}. Сначала запустите 01_fetch_primary.py")

    # Генерируем новую ключевую пару и CSR с тем же Subject, что у первичного сертификата.
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = load_subject_from_cert(primary_cert)

    csr = (
        x509.CertificateSigningRequestBuilder()
        .subject_name(subject)
        .sign(private_key, hashes.SHA256())
    )
    csr_pem = csr.public_bytes(serialization.Encoding.PEM).decode("utf-8")

    session = requests.Session()
    session.trust_env = False
    session.cert = (primary_cert, primary_key)
    # Для теста по IP отключаем проверку сертификата сервера (hostname mismatch).
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    session.verify = False

    url = f"{CONTROLLER_URL}{API_PREFIX}/cert"
    print(f"POST {url}")
    response = session.post(
        url,
        data=json.dumps({"csr": csr_pem}, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        timeout=10,
    )
    response.raise_for_status()
    data = response.json()

    if data.get("status") == "error":
        raise RuntimeError(f"backend error: {data.get('description')}")

    crt_pem = data.get("crt")
    if not crt_pem:
        raise RuntimeError("ответ не содержит crt")

    working_cert = os.path.join(OUT_DIR, "working_cert.pem")
    working_key = os.path.join(OUT_DIR, "working_key.pem")

    with open(working_key, "wb") as f:
        f.write(
            private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )
    os.chmod(working_key, 0o600)
    with open(working_cert, "w", encoding="utf-8") as f:
        f.write(crt_pem)

    print(f"OK: сохранено {working_cert}, {working_key}")


if __name__ == "__main__":
    main()
