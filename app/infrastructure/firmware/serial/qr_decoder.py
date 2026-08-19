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

Payload имеет TLV-структуру. Поля (п. 5.4.4 ТЗ):
  тип 0   — timestamp, uint32 LSBF, 4 байта (обязательное)
  тип 1   — MaxID, int64 LSBF, 8 байт (обязательно хотя бы одно из 1/2)
  тип 2   — телефон без "+7", int40 LSBF, 5 байт
  тип 4   — хеш телефона HMAC-SHA256(SHA256(PHONE), DYNAMIC_KEY), последние
            8 байт, int64 MSBF
  тип 128 — возрастная категория, uint8, 1 байт (0 — до 18 лет, 1 — 18+)
"""

import base64
import hashlib
import hmac
import os
import struct
from typing import Any

try:
    from cryptography.exceptions import InvalidSignature

    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives.serialization import (
        load_pem_private_key,
        load_pem_public_key,
    )
    CRYPTOGRAPHY_AVAILABLE = True
except ImportError:
    CRYPTOGRAPHY_AVAILABLE = False


def _phone_hash_field(phone: str, dynamic_key: bytes) -> bytes:
    """
    Вычислить содержимое поля типа 4: последние 8 байт
    HMAC-SHA256(SHA256(PHONE), DYNAMIC_KEY), где PHONE — строка вида
    "+79876543210" (п. 5.4.4 ТЗ).
    """
    digest = hashlib.sha256(phone.encode("ascii")).digest()
    full_hmac = hmac.new(dynamic_key, digest, hashlib.sha256).digest()
    return full_hmac[-8:]


def build_payload(
    timestamp: int,
    max_id: int,
    phone: int | None = None,
    phone_dynamic_key: bytes | None = None,
    age_category: int | None = None,
) -> bytes:
    """
    Собрать незашифрованный payload по формату ТЗ (п. 5.4.4).

    Parameters
    ----------
    timestamp : int
        Unix timestamp генерации QR (поле типа 0, обязательное).
    max_id : int
        MaxID пользователя (поле типа 1).
    phone : int, optional
        Номер телефона без "+7" как число (поле типа 2, 5 байт int40 LSBF).
    phone_dynamic_key : bytes, optional
        Если указан вместе с ``phone`` — вместо поля типа 2 (сырой номер)
        добавляется поле типа 4 (хеш телефона), если пользователь не дал
        согласие показывать номер в открытом виде.
    age_category : int, optional
        0 — младше 18 лет, 1 — 18+ (поле типа 128, 1 байт).
    """
    # Поле 0: timestamp, SIZE=6, TYPE=0, DATA=4 байта uint32 LSBF
    payload = bytes([6, 0]) + struct.pack("<I", timestamp)
    # Поле 1: max_id, SIZE=10, TYPE=1, DATA=8 байт int64 LSBF
    payload += bytes([10, 1]) + struct.pack("<q", max_id)

    if phone is not None:
        if phone_dynamic_key is not None:
            # Поле 4: хеш телефона, SIZE=10, TYPE=4, DATA=8 байт MSBF
            phone_str = f"+7{phone:010d}"
            content = _phone_hash_field(phone_str, phone_dynamic_key)
            payload += bytes([10, 4]) + content
        else:
            # Поле 2: телефон, SIZE=7, TYPE=2, DATA=5 байт int40 LSBF
            payload += bytes([7, 2]) + phone.to_bytes(5, "little")

    if age_category is not None:
        # Поле 128: возрастная категория, SIZE=3, TYPE=128, DATA=1 байт
        payload += bytes([3, 128, age_category])

    return payload


_DEFAULT_QR_BASE_URL = "https://pass.lipetsk.ru/?"


def encode_qr(
    key_id: int,
    timestamp: int,
    max_id: int,
    private_key_pem: str | bytes,
    shared_key_raw: str | bytes,
    phone: int | None = None,
    phone_dynamic_key: str | bytes | None = None,
    age_category: int | None = None,
    qr_base_url: str = _DEFAULT_QR_BASE_URL,
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
    phone : int, optional
        Номер телефона без "+7" как число (поле типа 2 либо 4, см. build_payload).
    phone_dynamic_key : str | bytes, optional
        DYNAMIC_KEY для поля типа 4 (хеш телефона) — если указан вместе с
        ``phone``, номер передаётся хешированным, а не в открытом виде.
    age_category : int, optional
        0 — младше 18 лет, 1 — 18+.

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

    if len(shared_key_raw) == 16:
        # Уже сырые 16 байт ключа — ничего не трогаем. Важно проверять ЭТО
        # раньше strip()/b64decode: strip() на бинарных данных может
        # случайно откусить байты, совпадающие с ASCII-пробельными символами,
        # а b64decode может "успешно" дать мусор другой длины.
        shared_key = shared_key_raw
    else:
        stripped = shared_key_raw.strip()
        try:
            shared_key = base64.b64decode(stripped)
        except Exception:  # noqa: BLE001
            shared_key = stripped

    if len(shared_key) != 16:
        raise ValueError("Shared key должен быть ровно 16 байт")

    if isinstance(phone_dynamic_key, str):
        phone_dynamic_key = phone_dynamic_key.encode("utf-8")

    private_key = load_pem_private_key(private_key_pem, password=None)

    payload = build_payload(
        timestamp, max_id,
        phone=phone, phone_dynamic_key=phone_dynamic_key, age_category=age_category,
    )

    nonce = os.urandom(4)
    iv = nonce + b"\x00" * 12
    cipher = Cipher(algorithms.AES(shared_key), modes.CTR(iv))
    encryptor = cipher.encryptor()
    ciphertext = encryptor.update(payload) + encryptor.finalize()

    msg = bytes([0, key_id]) + nonce + ciphertext
    signature = private_key.sign(msg)
    full_frame = msg + signature

    b64 = base64.urlsafe_b64encode(full_frame).decode("ascii").rstrip("=")
    return f"{qr_base_url}{b64}"


class QRDecoder:
    """Декодер и верификатор QR-кодов доступа.

    Ключи хранятся только в оперативной памяти (согласно ТЗ) и
    загружаются через ``set_keys()`` после получения от бэкенда.
    """

    def __init__(self, qr_base_url: str = _DEFAULT_QR_BASE_URL) -> None:
        """Инициализировать декодер (без ключей — загружаются позже)."""
        if not CRYPTOGRAPHY_AVAILABLE:
            raise ImportError("Модуль cryptography не установлен. Установите: pip install cryptography")
        self._qr_base_url = qr_base_url
        # {key_id: (public_key, shared_key_bytes)}
        self._keys: dict[int, tuple[Any, bytes]] = {}

    def set_keys(self, key_id: int, public_key: Any, shared_key: bytes) -> None:
        """Загрузить набор ключей в память."""
        self._keys[key_id] = (public_key, shared_key)

    def remove_keys(self, key_id: int) -> None:
        """Удалить набор ключей из памяти."""
        self._keys.pop(key_id, None)

    def has_keys(self) -> bool:
        """Есть ли хотя бы один набор ключей."""
        return bool(self._keys)

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
        except Exception as e:  # noqa: BLE001
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
                # Телефон без "+7", int40 LSBF, 5 байт.
                if len(content) == 5:
                    number = int.from_bytes(content, "little")
                    fields["phone"] = f"+7{number:010d}"
                else:
                    fields["phone_raw"] = content
            elif field_type == 4:
                # Хеш телефона: последние 8 байт HMAC-SHA256(SHA256(PHONE), DYNAMIC_KEY), MSBF.
                if len(content) == 8:
                    fields["phone_hash"] = content.hex()
                else:
                    fields["phone_hash_raw"] = content
            elif field_type == 128:
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
        """Получить публичный и общий ключи для key_id из памяти."""
        if key_id not in self._keys:
            raise KeyError(f"Ключи для ID {key_id} не загружены (доступны: {list(self._keys)})")
        return self._keys[key_id]
