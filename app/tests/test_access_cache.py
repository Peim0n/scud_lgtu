"""Тесты LocalAccessCache — обновление и проверка списка доступа (п. 5.4.3, 5.5 ТЗ)."""
from app.infrastructure.cache.access_cache import LocalAccessCache
from app.infrastructure.cache.identifier_hash import hash_identifier

STATIC_KEY = "0123456789abcdef0123456789abcdef"
DYNAMIC_KEY = "fedcba9876543210fedcba9876543210"


def test_raw_type_from_backend_is_hashed_and_matched():
    """
    Реальный dev-backend отдаёт "phone"/"maxid" в сыром виде (без суффикса
    "_h", см. access/get). Кэш должен захешировать их при загрузке, иначе
    is_allowed() (который всегда хеширует входящий токен для не-"_h" типов)
    никогда не найдёт совпадение.
    """
    cache = LocalAccessCache(static_key=STATIC_KEY, dynamic_key=DYNAMIC_KEY)
    cache.update({
        "status": "ok",
        "id": [{"type": "phone", "quantity": 1, "list": ["+79006008913"]}],
    })

    allowed, user_id = cache.is_allowed("phone", "+79006008913")

    assert allowed is True
    assert user_id is None


def test_raw_type_rejects_unknown_value():
    cache = LocalAccessCache(static_key=STATIC_KEY, dynamic_key=DYNAMIC_KEY)
    cache.update({
        "status": "ok",
        "id": [{"type": "maxid", "quantity": 1, "list": ["1234567"]}],
    })

    allowed, _ = cache.is_allowed("maxid", "7654321")

    assert allowed is False


def test_already_hashed_type_from_backend_is_stored_as_is():
    """Тип с суффиксом "_h" уже хеширован бэкендом — повторно хешировать не нужно."""
    precomputed_hash = hash_identifier("1234567", STATIC_KEY, DYNAMIC_KEY)
    cache = LocalAccessCache(static_key=STATIC_KEY, dynamic_key=DYNAMIC_KEY)
    cache.update({
        "status": "ok",
        "id": [{"type": "maxid_h", "quantity": 1, "list": [precomputed_hash]}],
    })

    allowed, _ = cache.is_allowed("maxid_h", precomputed_hash)

    assert allowed is True


def test_update_without_keys_falls_back_to_raw_comparison():
    """Без static_key/dynamic_key (например, до первой синхронизации ключей) _hash() не хеширует — сравнение идёт по сырым значениям."""
    cache = LocalAccessCache()
    cache.update({
        "status": "ok",
        "id": [{"type": "phone", "quantity": 1, "list": ["+79006008913"]}],
    })

    allowed, _ = cache.is_allowed("phone", "+79006008913")

    assert allowed is True
