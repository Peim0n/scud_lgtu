#!/usr/bin/env python3
"""
Скрипт для генерации QR-кода доступа (симулятор системы выпуска QR — нужен
только для офлайн-тестирования QR-считывателя/QRDecoder, к рантайму
приложения не относится).

ВАЖНО: само приложение (QRDecoder) НИКОГДА не хранит и не читает ключи с
диска — только в памяти, полученные от бэкенда через KeySyncService
(см. app/infrastructure/firmware/serial/qr_decoder.py). Ключи в QR_KEYS_DIR
ниже — это локальный тестовый набор для данного скрипта, в config.yml
приложения такого параметра нет и быть не должно.

Использование:
    python generate_qr.py <max_id> [key_id]

Пример:
    python generate_qr.py 12345 13

Переменные окружения:
    QR_KEYS_DIR - где лежат тестовые ключи (по умолчанию ./qr_test_keys,
                  см. .gitignore — эта директория не должна попадать в git)
"""
import os
import sys
import time

from app.infrastructure.firmware.serial.qr_decoder import encode_qr


def main():
    if len(sys.argv) < 2:
        print("Использование: python generate_qr.py <max_id> [key_id]")
        print("Пример: python generate_qr.py 12345 13")
        sys.exit(1)

    max_id = int(sys.argv[1])
    key_id = int(sys.argv[2]) if len(sys.argv) > 2 else 13

    script_dir = os.path.dirname(os.path.abspath(__file__))
    keys_dir = os.environ.get("QR_KEYS_DIR", os.path.join(script_dir, "qr_test_keys"))
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
