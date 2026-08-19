"""
Тесты кодирования/декодирования QR-кодов (п. 5.4.4 ТЗ), включая регрессию
на баг с типами полей: тип 2 — телефон (не возрастная категория!),
тип 4 — хеш телефона, тип 128 — возрастная категория.
"""
import hashlib
import hmac
import os

import pytest
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

from app.infrastructure.firmware.serial.qr_decoder import (
    QRDecoder,
    _phone_hash_field,
    build_payload,
    encode_qr,
)

SHARED_KEY = os.urandom(16)
DYNAMIC_KEY = os.urandom(16)


@pytest.fixture
def qr_keys():
    """Генерирует пару ключей и возвращает (priv_pem, QRDecoder с загруженными ключами)."""
    private_key = ed25519.Ed25519PrivateKey.generate()
    public_key = private_key.public_key()

    priv_pem = private_key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())

    decoder = QRDecoder()
    decoder.set_keys(1, public_key, SHARED_KEY)

    return decoder, priv_pem


def test_field_type_2_is_phone_number_matches_tz_example():
    """Пример из ТЗ: +7 987 654 32 10 -> EA 16 B0 4C 02 (int40 LSBF)."""
    payload = build_payload(timestamp=0, max_id=0, phone=9876543210)
    # Поле 0 (timestamp, 6 байт) + поле 1 (max_id, 10 байт) идут первыми,
    # затем поле телефона.
    phone_field = payload[16:]
    assert phone_field[0] == 7  # SIZE
    assert phone_field[1] == 2  # TYPE
    assert phone_field[2:7] == bytes.fromhex("EA16B04C02")


def test_field_type_128_is_age_category_not_2():
    payload = build_payload(timestamp=0, max_id=0, age_category=1)
    age_field = payload[16:]
    assert age_field[0] == 3   # SIZE
    assert age_field[1] == 128  # TYPE (не 2!)
    assert age_field[2] == 1


def test_decode_roundtrip_phone_raw(qr_keys):
    decoder, priv_pem = qr_keys
    url = encode_qr(
        key_id=1, timestamp=1748772021, max_id=1315784,
        private_key_pem=priv_pem, shared_key_raw=SHARED_KEY,
        phone=9876543210,
    )
    fields = decoder.decode_url(url)

    assert fields["max_id"] == 1315784
    assert fields["timestamp"] == 1748772021
    assert fields["phone"] == "+79876543210"
    assert "age_category" not in fields


def test_decode_roundtrip_phone_hash(qr_keys):
    decoder, priv_pem = qr_keys
    url = encode_qr(
        key_id=1, timestamp=1748772021, max_id=1315784,
        private_key_pem=priv_pem, shared_key_raw=SHARED_KEY,
        phone=9876543210, phone_dynamic_key=DYNAMIC_KEY,
    )
    fields = decoder.decode_url(url)

    assert "phone" not in fields  # номер не передан в открытом виде
    assert "phone_hash" in fields
    expected = hmac.new(
        DYNAMIC_KEY, hashlib.sha256(b"+79876543210").digest(), hashlib.sha256
    ).digest()[-8:].hex()
    assert fields["phone_hash"] == expected


def test_decode_roundtrip_age_category(qr_keys):
    decoder, priv_pem = qr_keys
    url = encode_qr(
        key_id=1, timestamp=1748772021, max_id=1315784,
        private_key_pem=priv_pem, shared_key_raw=SHARED_KEY,
        age_category=1,
    )
    fields = decoder.decode_url(url)

    assert fields["age_category"] == "18+"


def test_decode_roundtrip_all_fields_together(qr_keys):
    decoder, priv_pem = qr_keys
    url = encode_qr(
        key_id=1, timestamp=1748772021, max_id=1315784,
        private_key_pem=priv_pem, shared_key_raw=SHARED_KEY,
        phone=9876543210, age_category=0,
    )
    fields = decoder.decode_url(url)

    assert fields["max_id"] == 1315784
    assert fields["phone"] == "+79876543210"
    assert fields["age_category"] == "under 18"


def test_phone_hash_field_helper_matches_formula():
    result = _phone_hash_field("+79876543210", DYNAMIC_KEY)
    expected = hmac.new(
        DYNAMIC_KEY, hashlib.sha256(b"+79876543210").digest(), hashlib.sha256
    ).digest()[-8:]
    assert result == expected
    assert len(result) == 8
