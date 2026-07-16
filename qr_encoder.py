"""
Кодер QR-кодов СКУД.

Собирает payload, шифрует AES128-CTR, подписывает Ed25519 и возвращает
URL-safe base64 строку.
"""

import base64
import os
import struct
from typing import Union

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.serialization import load_pem_private_key


def build_payload(timestamp: int, max_id: int) -> bytes:
    """Собрать незашифрованный payload по формату ТЗ."""
    # Поле 0: timestamp, SIZE=6, TYPE=0, DATA=4 байта uint32 LSBF
    field_0 = bytes([6, 0]) + struct.pack("<I", timestamp)
    # Поле 1: max_id, SIZE=10, TYPE=1, DATA=8 байт uint64 LSBF
    field_1 = bytes([10, 1]) + struct.pack("<Q", max_id)
    return field_0 + field_1


def encode_qr(
    key_id: int,
    timestamp: int,
    max_id: int,
    private_key_pem: Union[str, bytes],
    shared_key_raw: Union[str, bytes],
) -> str:
    """
    Закодировать QR URL.

    Parameters
    ----------
    key_id : int
        Номер набора ключей 0-182.
    timestamp : int
        Unix timestamp.
    max_id : int
        MaxID пользователя.
    private_key_pem : str | bytes
        PEM-Encoded Ed25519 private key.
    shared_key_raw : str | bytes
        AES shared key (16 bytes or base64).

    Returns
    -------
    str
        Полный URL QR-кода.
    """
    if isinstance(private_key_pem, str):
        private_key_pem = private_key_pem.encode("utf-8")

    if isinstance(shared_key_raw, str):
        shared_key_raw = shared_key_raw.encode("utf-8")

    shared_key_raw = shared_key_raw.strip()
    try:
        shared_key = base64.b64decode(shared_key_raw)
    except Exception:
        shared_key = shared_key_raw

    if len(shared_key) != 16:
        raise ValueError("Shared key должен быть ровно 16 байт")

    private_key = load_pem_private_key(private_key_pem, password=None)

    payload = build_payload(timestamp, max_id)

    nonce = os.urandom(4)
    iv = nonce + b"\x00" * 12
    cipher = Cipher(algorithms.AES(shared_key), modes.CTR(iv))
    encryptor = cipher.encryptor()
    ciphertext = encryptor.update(payload) + encryptor.finalize()

    msg = bytes([0, key_id]) + nonce + ciphertext
    signature = private_key.sign(msg)
    full_frame = msg + signature

    b64 = base64.urlsafe_b64encode(full_frame).decode("ascii").rstrip("=")
    return f"https://pass.lipetsk.ru/?{b64}"
