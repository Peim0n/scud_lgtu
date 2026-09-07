"""
Хеширование идентификаторов доступа по ТЗ.

Формула (одинаковая для maxid, phone, cardid):
    HMAC_SHA256(HMAC_SHA256(SHA256(value), STATIC_KEY), DYNAMIC_KEY)

STATIC_KEY — уникален для точки доступа, загружается на все считыватели.
DYNAMIC_KEY — меняется ежедневно, передаётся контроллером с бэкенда.
"""

import hashlib
import hmac
from typing import Any


def _to_bytes(value: str | bytes) -> bytes:
    """Привести значение к bytes для хеширования."""
    if isinstance(value, str):
        return value.encode("utf-8")
    return value


def hash_identifier(
    value: str | bytes,
    static_key: str | bytes,
    dynamic_key: str | bytes,
) -> str:
    """
    Вычислить хеш идентификатора по формуле ТЗ.

    Используется для идентификаторов, которые приходят в СЫРОМ виде
    (например, MaxID, телефон) — все три шага (SHA256 + HMAC(STATIC_KEY) +
    HMAC(DYNAMIC_KEY)) выполняются здесь.

    ВНИМАНИЕ: не подходит для карт, считанных Wiegand-ридером в режиме
    аппаратного хеширования (см. ``hash_partial_identifier``) — там первые
    два шага уже выполнены самим считывателем.

    Parameters
    ----------
    value : str | bytes
        Исходный идентификатор (например, PAN, MaxID, телефон).
    static_key : str | bytes
        Статический ключ точки доступа.
    dynamic_key : str | bytes
        Динамический ключ дня.

    Returns
    -------
    str
        Хеш в hex (64 символа).
    """
    value_b = _to_bytes(value)
    static_b = _to_bytes(static_key)
    dynamic_b = _to_bytes(dynamic_key)

    step1 = hashlib.sha256(value_b).digest()
    step2 = hmac.new(static_b, step1, hashlib.sha256).digest()
    step3 = hmac.new(dynamic_b, step2, hashlib.sha256).hexdigest()
    return step3


def hash_partial_identifier(
    partial_hash: str | bytes | int,
    dynamic_key: str | bytes,
    partial_hash_size: int = 8,
) -> str:
    """
    Довычислить хеш карты, для которой шаги SHA256+HMAC(STATIC_KEY) уже
    выполнены самим считывателем (Wiegand-ридеры типа ЭРА в режиме
    "HMAC-SHA256(SHA256(PAN), KEY)", обрезающие результат до 8 байт для
    передачи по Wiegand).

    Выполняет только оставшийся третий шаг формулы ТЗ:
    ``HMAC_SHA256(partial_hash, DYNAMIC_KEY)``.

    Parameters
    ----------
    partial_hash : str | bytes | int
        Значение, полученное от считывателя (``card_data``). Если передано
        как ``int`` или десятичная строка — приводится к ``partial_hash_size``
        байтам big-endian перед хешированием.
    dynamic_key : str | bytes
        Динамический ключ дня.
    partial_hash_size : int, optional
        Размер значения от считывателя в байтах (по умолчанию 8 — под
        Wiegand-кадр ``era_mf_64_hash``).

    Returns
    -------
    str
        Хеш в hex (64 символа), сравнимый со значениями ``cardid_h`` от бэкенда
        (при условии, что бэкенд считает cardid_h той же усечённой схемой).
    """
    if isinstance(partial_hash, int):
        partial_b = partial_hash.to_bytes(partial_hash_size, "big")
    elif isinstance(partial_hash, str):
        try:
            partial_b = int(partial_hash).to_bytes(partial_hash_size, "big")
        except ValueError:
            # Уже hex-строка
            partial_b = bytes.fromhex(partial_hash)
    else:
        partial_b = partial_hash

    dynamic_b = _to_bytes(dynamic_key)
    return hmac.new(dynamic_b, partial_b, hashlib.sha256).hexdigest()


def normalize(value: Any) -> str:
    """Нормализовать идентификатор для хеширования."""
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    return str(value).strip()
