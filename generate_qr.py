#!/usr/bin/env python3
"""
Скрипт для генерации QR-кода доступа.

Использование:
    python generate_qr.py <max_id> [key_id]

Пример:
    python generate_qr.py 12345 13
"""
import sys
import time
import os
from scud_lgtu.infrastructure.serial.qr_codec import encode_qr


def main():
    if len(sys.argv) < 2:
        print("Использование: python generate_qr.py <max_id> [key_id]")
        print("Пример: python generate_qr.py 12345 13")
        sys.exit(1)

    max_id = int(sys.argv[1])
    key_id = int(sys.argv[2]) if len(sys.argv) > 2 else 13

    # Загружаем ключи
    keys_dir = "scud_lgtu/key"
    private_key_path = os.path.join(keys_dir, f"private_key.{key_id}")
    shared_key_path = os.path.join(keys_dir, f"shared_key.{key_id}")

    if not os.path.exists(private_key_path):
        print(f"Ошибка: файл приватного ключа не найден: {private_key_path}")
        sys.exit(1)

    if not os.path.exists(shared_key_path):
        print(f"Ошибка: файл общего ключа не найден: {shared_key_path}")
        sys.exit(1)

    with open(private_key_path, "r") as f:
        private_key_pem = f.read()

    with open(shared_key_path, "r") as f:
        shared_key_raw = f.read()

    # Генерируем QR код
    timestamp = int(time.time())
    qr_url = encode_qr(
        key_id=key_id,
        timestamp=timestamp,
        max_id=max_id,
        private_key_pem=private_key_pem,
        shared_key_raw=shared_key_raw,
    )

    print(f"QR URL для max_id={max_id}, key_id={key_id}:")
    print(qr_url)
    print(f"\nTimestamp: {timestamp}")
    print(f"MaxID: {max_id}")
    print(f"Key ID: {key_id}")


if __name__ == "__main__":
    main()
