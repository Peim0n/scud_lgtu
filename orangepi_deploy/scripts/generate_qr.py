#!/usr/bin/env python3
"""
Генератор тестовых QR-кодов.

Использует только сгенерированные наборы ключей из key/.
В отличие от Makefile, не выбирает случайный KEYSET — по умолчанию
использует ключ за сегодня, чтобы QR декодировался актуальным набором.

Примеры:
  python scripts/generate_qr.py 12345
  python scripts/generate_qr.py 12345 --png code.png
  python scripts/generate_qr.py 12345 --keyset 167
  python scripts/generate_qr.py 12345 --time 1752510000
"""

import argparse
import os
import subprocess
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from qr_encoder import encode_qr


def key_id_for_date(date: datetime) -> int:
    """Номер набора ключей по дате."""
    return date.timetuple().tm_yday % 183


def generate_qr_url(key_id: int, timestamp: int, max_id: int, keys_dir: str = "key") -> str:
    """Сгенерировать полный URL с QR."""
    private_path = os.path.join(keys_dir, f"private_key.{key_id}")
    shared_path = os.path.join(keys_dir, f"shared_key.{key_id}")

    if not os.path.exists(private_path) or not os.path.exists(shared_path):
        raise FileNotFoundError(f"Ключи для набора {key_id} не найдены в {keys_dir}")

    with open(private_path, "rb") as f:
        private_key_pem = f.read()
    with open(shared_path, "rb") as f:
        shared_key_raw = f.read()

    return encode_qr(key_id, timestamp, max_id, private_key_pem, shared_key_raw)


def generate_png(url: str, output_path: str) -> None:
    """Сгенерировать PNG через qrencode, если доступен."""
    try:
        subprocess.run(
            ["qrencode", "-l", "H", "-t", "PNG", "-o", output_path, url],
            check=True,
        )
        print(f"PNG сохранён: {output_path}")
    except FileNotFoundError:
        raise RuntimeError("qrencode не установлен. Установи: sudo apt install qrencode")


def main() -> None:
    """CLI для генерации тестовых QR-кодов."""
    parser = argparse.ArgumentParser(description="Генератор тестовых QR-кодов")
    parser.add_argument("max_id", type=int, help="MaxID пользователя")
    parser.add_argument("--time", type=int, default=None, help="Unix timestamp (по умолчанию now)")
    parser.add_argument("--keyset", type=int, default=None, help="Номер набора ключей 0-182 (по умолчанию сегодня)")
    parser.add_argument("--keys-dir", type=str, default="key", help="Директория с ключами")
    parser.add_argument("--png", type=str, default=None, help="Сохранить PNG в файл")
    args = parser.parse_args()

    timestamp = args.time if args.time is not None else int(datetime.now().timestamp())
    key_id = args.keyset if args.keyset is not None else key_id_for_date(datetime.now())

    if not 0 <= key_id <= 182:
        print("Ошибка: keyset должен быть 0-182", file=sys.stderr)
        sys.exit(1)

    url = generate_qr_url(key_id, timestamp, args.max_id, args.keys_dir)
    print(url)

    if args.png:
        generate_png(url, args.png)


if __name__ == "__main__":
    main()
