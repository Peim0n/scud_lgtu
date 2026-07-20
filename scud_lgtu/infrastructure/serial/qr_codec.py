"""
Кодер и декодер QR-кодов СКУД.

Кодер собирает payload, шифрует AES128-CTR, подписывает Ed25519 и возвращает
URL-safe base64 строку.

Декодер верифицирует подпись, расшифровывает и парсит TLV-структуру.

Формат QR
---------
URL вида ``https://pass.lipetsk.ru/?<urlsafe_base64_payload>``.

Структура фрейма (минимум 70 байт):
  1 байт  — версия протокола (0x00)
  1 байт  — ID набора ключей
  4 байта — nonce (uint32 LSBF)
  ...     — шифрованный payload (AES128-CTR)
  64 байта — подпись Ed25519

Payload имеет TLV-структуру. Обязательные поля:
  тип 0 — timestamp (uint32 LSBF)
  тип 1 — MaxID (int64 LSBF)
"""

import base64
import os
import struct
from typing import Any, Union

try:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives.asymmetric import ed25519
    from cryptography.hazmat.primitives.serialization import load_pem_private_key, load_pem_public_key
    from cryptography.exceptions import InvalidSignature
    CRYPTOGRAPHY_AVAILABLE = True
except ImportError:
    CRYPTOGRAPHY_AVAILABLE = False


def build_payload(timestamp: int, max_id: int) -> bytes:
    """Собрать незашифрованный payload по формату ТЗ."""
    # Поле 0: timestamp, SIZE=6, TYPE=0, DATA=4 байта uint32 LSBF
    field_0 = bytes([6, 0]) + struct.pack("<I", timestamp)
    # Поле 1: max_id, SIZE=10, TYPE=1, DATA=8 байт int64 LSBF
    field_1 = bytes([10, 1]) + struct.pack("<q", max_id)
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
    if not CRYPTOGRAPHY_AVAILABLE:
        raise ImportError("Модуль cryptography не установлен. Установите: pip install cryptography")

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


class QRDecoder:
    """Декодер и верификатор QR-кодов доступа."""

    def __init__(self, keys_dir: str = "key") -> None:
        """Инициализировать декодер с директорией ключей."""
        if not CRYPTOGRAPHY_AVAILABLE:
            raise ImportError("Модуль cryptography не установлен. Установите: pip install cryptography")
        self._keys_dir = keys_dir

    def decode_url(self, full_url: str, expected_head: str | None = None) -> dict[str, Any]:
        """
        Декодировать сообщение из полного URL.

        Parameters
        ----------
        full_url : str
            URL вида ``https://pass.lipetsk.ru/?base64_payload``.
        expected_head : str, optional
            Ожидаемый заголовок URL для проверки.

        Returns
        -------
        dict
            Расшифрованные поля payload.
        """
        if "?" not in full_url:
            raise ValueError("URL должен содержать '?' перед payload")

        head, payload_b64 = full_url.split("?", 1)
        if expected_head is not None and head + "?" != expected_head:
            raise ValueError(f"Заголовок URL не совпадает: {head}")

        return self._process(payload_b64)

    def decode_payload(self, payload_b64: str) -> dict[str, Any]:
        """Декодировать только base64 payload."""
        return self._process(payload_b64)

    def _process(self, payload_b64: str) -> dict[str, Any]:
        """Декодировать, проверить подпись и расшифровать payload."""
        # Добавляем padding при необходимости
        missing_padding = len(payload_b64) % 4
        if missing_padding:
            payload_b64 += "=" * (4 - missing_padding)

        try:
            full_frame = base64.urlsafe_b64decode(payload_b64)
        except Exception as e:
            raise ValueError(f"Ошибка декодирования base64: {e}")

        if len(full_frame) < 70:
            raise ValueError("Слишком короткий фрейм")

        version = full_frame[0]
        key_id = full_frame[1]
        signature = full_frame[-64:]
        msg_to_sign = full_frame[:-64]
        nonce = msg_to_sign[2:6]
        ciphertext = msg_to_sign[6:]

        if version != 0x00:
            raise ValueError(f"Неподдерживаемая версия протокола: {version}")

        public_key, shared_key = self._load_keys(key_id)

        # Верификация подписи
        try:
            public_key.verify(signature, msg_to_sign)
        except InvalidSignature:
            raise ValueError("Цифровая подпись невалидна")

        # Дешифрование AES128-CTR
        iv = nonce + b"\x00" * 12
        cipher = Cipher(algorithms.AES(shared_key), modes.CTR(iv))
        decryptor = cipher.decryptor()
        decrypted_payload = decryptor.update(ciphertext) + decryptor.finalize()

        return self._parse_payload(decrypted_payload)

    def _parse_payload(self, payload: bytes) -> dict[str, Any]:
        """Парсинг TLV-структуры расшифрованного payload."""
        fields: dict[str, Any] = {}
        offset = 0

        while offset < len(payload):
            if offset + 2 > len(payload):
                break

            size = payload[offset]
            field_type = payload[offset + 1]

            if size < 2:
                raise ValueError(f"Некорректный размер поля на смещении {offset}: {size}")

            content_size = size - 2
            content = payload[offset + 2 : offset + size]

            if len(content) < content_size:
                raise ValueError(f"Недостаточно данных для поля типа {field_type}")

            if field_type == 0:
                if len(content) == 4:
                    fields["timestamp"] = struct.unpack("<I", content)[0]
                else:
                    fields["timestamp_raw"] = content
            elif field_type == 1:
                if len(content) == 8:
                    fields["max_id"] = struct.unpack("<Q", content)[0]
                else:
                    fields["max_id_raw"] = content
            elif field_type == 2:
                if len(content) == 1:
                    val = content[0]
                    fields["age_category"] = "18+" if val == 1 else "under 18"
                else:
                    fields["age_category_raw"] = content
            else:
                fields[f"field_{field_type}"] = content

            offset += size

        return fields

    def _load_keys(self, key_id: int) -> tuple:
        """Загрузить публичный и общий ключи для key_id."""
        pub_path = os.path.join(self._keys_dir, f"public_key.{key_id}")
        shared_path = os.path.join(self._keys_dir, f"shared_key.{key_id}")

        if not os.path.exists(pub_path) or not os.path.exists(shared_path):
            raise FileNotFoundError(f"Ключи для ID {key_id} не найдены в {self._keys_dir}")

        with open(pub_path, "rb") as f:
            public_key = load_pem_public_key(f.read())

        with open(shared_path, "rb") as f:
            shared_key_raw = f.read().strip()
            try:
                shared_key = base64.b64decode(shared_key_raw)
            except Exception:
                shared_key = shared_key_raw

        return public_key, shared_key
