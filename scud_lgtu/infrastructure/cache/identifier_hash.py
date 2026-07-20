"""
Хеширование идентификаторов доступа по ТЗ.

Формула (одинаковая для maxid, phone, cardid):
    HMAC_SHA256(HMAC_SHA256(SHA256(value), STATIC_KEY), DYNAMIC_KEY)

STATIC_KEY — уникален для точки доступа, загружается на все считыватели.
DYNAMIC_KEY — меняется ежедневно, передаётся контроллером с бэкенда.
"""

import hashlib
import hmac
from typing import Union


def _to_bytes(value: Union[str, bytes]) -> bytes:
    """Привести значение к bytes для хеширования."""
    if isinstance(value, str):
        return value.encode("utf-8")
    return value


def hash_identifier(
    value: Union[str, bytes],
    static_key: Union[str, bytes],
    dynamic_key: Union[str, bytes],
) -> str:
    """
    Вычислить хеш идентификатора по формуле ТЗ.

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


def normalize(value: Union[str, bytes]) -> str:
    """Нормализовать идентификатор для хеширования."""
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    return value.strip()
