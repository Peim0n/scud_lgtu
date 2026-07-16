#!/usr/bin/env python3
"""
Генерация ключевых наборов для QR-кодов.

Совместимо с Makefile из примера QR. Создаёт файлы:
  key/shared_key.{key_id}
  key/private_key.{key_id}
  key/public_key.{key_id}

По умолчанию генерирует 31 набор ключей (актуальный + 30 предыдущих),
чтобы QR, созданный Makefile с любым KEYSET из последних 30 дней,
мог быть декодирован.
"""

import argparse
import base64
import os
import sys
from datetime import datetime, timedelta

from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    PrivateFormat,
    PublicFormat,
    NoEncryption,
)


def key_id_for_date(date: datetime) -> int:
    """Номер набора ключей по дате: остаток от деления номера дня в году на 183."""
    return date.timetuple().tm_yday % 183


def generate_keyset(key_id: int, keys_dir: str) -> None:
    """Сгенерировать один набор ключей."""
    os.makedirs(keys_dir, exist_ok=True)

    private_key = ed25519.Ed25519PrivateKey.generate()
    public_key = private_key.public_key()

    shared_key = os.urandom(16)

    shared_path = os.path.join(keys_dir, f"shared_key.{key_id}")
    private_path = os.path.join(keys_dir, f"private_key.{key_id}")
    public_path = os.path.join(keys_dir, f"public_key.{key_id}")

    with open(shared_path, "wb") as f:
        f.write(base64.b64encode(shared_key))

    private_pem = private_key.private_bytes(
        encoding=Encoding.PEM,
        format=PrivateFormat.PKCS8,
        encryption_algorithm=NoEncryption(),
    )
    with open(private_path, "wb") as f:
        f.write(private_pem)

    public_pem = public_key.public_bytes(
        encoding=Encoding.PEM,
        format=PublicFormat.SubjectPublicKeyInfo,
    )
    with open(public_path, "wb") as f:
        f.write(public_pem)

    print(f"keyset {key_id}: {shared_path}, {private_path}, {public_path}")


def main() -> None:
    """CLI для генерации ключевых наборов за заданное число дней."""
    parser = argparse.ArgumentParser(description="Генерация ключевых наборов QR")
    parser.add_argument("--days", type=int, default=31, help="Количество дней назад (по умолчанию 31)")
    parser.add_argument("--keys-dir", type=str, default="key", help="Директория для ключей")
    args = parser.parse_args()

    today = datetime.now()
    generated = set()

    for i in range(args.days):
        date = today - timedelta(days=i)
        key_id = key_id_for_date(date)
        if key_id in generated:
            continue
        generated.add(key_id)
        generate_keyset(key_id, args.keys_dir)

    print(f"\nСгенерировано наборов: {len(generated)}")


if __name__ == "__main__":
    main()
