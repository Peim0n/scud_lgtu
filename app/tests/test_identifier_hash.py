"""
Тесты хеширования идентификаторов карт (п. 5.4.3 ТЗ) с учётом того, что
Wiegand-ридер (ЭРА и аналоги, режим "HMAC-SHA256(SHA256(PAN), KEY)")
уже выполняет первые два шага формулы и отдаёт только 8 байт (64 бита).

Проверяем: значение, пришедшее по Wiegand (card_data), после довычисления
финального HMAC(..., DYNAMIC_KEY) через LocalAccessCache, совпадает с тем,
что backend должен был бы прислать как cardid_h, если считает cardid_h
той же усечённой схемой (SHA256(PAN) -> HMAC(STATIC_KEY) -> обрезать до 8
байт -> HMAC(DYNAMIC_KEY)).
"""
import hashlib
import hmac

from app.infrastructure.cache.access_cache import LocalAccessCache
from app.infrastructure.cache.identifier_hash import hash_partial_identifier

STATIC_KEY = "0123456789abcdef0123456789abcdef"
DYNAMIC_KEY = "fedcba9876543210fedcba9876543210"
PAN = "2200123412341234"  # тестовый номер карты МИР


def _reader_side_partial_hash(pan: str, static_key: str) -> int:
    """Смоделировать то, что делает Wiegand-ридер ЭРА в режиме
    'HMAC-SHA256(SHA256(PAN), KEY)': SHA256 -> HMAC(STATIC_KEY) -> обрезать
    до младших 8 байт (64 значащих бита после сдвига на 0, как на скрине
    конфигуратора)."""
    step1 = hashlib.sha256(pan.encode("utf-8")).digest()
    step2 = hmac.new(static_key.encode("utf-8"), step1, hashlib.sha256).digest()
    truncated = step2[-8:]  # младшие 8 байт
    return int.from_bytes(truncated, "big")


def _backend_side_cardid_h(pan: str, static_key: str, dynamic_key: str) -> str:
    """Смоделировать то, что backend ДОЛЖЕН считать для cardid_h, если он
    учитывает усечение до 8 байт, которое неизбежно из-за Wiegand."""
    truncated_int = _reader_side_partial_hash(pan, static_key)
    truncated_bytes = truncated_int.to_bytes(8, "big")
    return hmac.new(dynamic_key.encode("utf-8"), truncated_bytes, hashlib.sha256).hexdigest()


def test_hash_partial_identifier_matches_backend_scheme():
    """hash_partial_identifier() должен давать тот же результат, что и
    полный расчёт (SHA256+HMAC(STATIC)+обрезка+HMAC(DYNAMIC)) на стороне
    backend, если на вход подать то, что реально пришло с Wiegand."""
    card_data = _reader_side_partial_hash(PAN, STATIC_KEY)
    expected = _backend_side_cardid_h(PAN, STATIC_KEY, DYNAMIC_KEY)

    actual = hash_partial_identifier(card_data, DYNAMIC_KEY)

    assert actual == expected


def test_local_access_cache_accepts_card_from_wiegand():
    """Полный путь: card_data от Wiegand -> LocalAccessCache.is_allowed()
    с типом cardid_partial_h -> должен найти совпадение в списке cardid_h,
    присланном backend."""
    card_data = _reader_side_partial_hash(PAN, STATIC_KEY)
    cardid_h = _backend_side_cardid_h(PAN, STATIC_KEY, DYNAMIC_KEY)

    cache = LocalAccessCache(static_key=STATIC_KEY, dynamic_key=DYNAMIC_KEY)
    cache.update({
        "id": [
            {"type": "cardid_h", "quantity": 1, "list": [cardid_h]},
        ],
        "users": {"42": {"cardid_h": cardid_h}},
    })

    allowed, user_id = cache.is_allowed("cardid_partial_h", str(card_data))

    assert allowed is True
    assert user_id == 42


def test_local_access_cache_rejects_unknown_card():
    """Карта, не попавшая в список cardid_h, не должна проходить."""
    card_data = _reader_side_partial_hash(PAN, STATIC_KEY)
    other_cardid_h = _backend_side_cardid_h("9999999999999999", STATIC_KEY, DYNAMIC_KEY)

    cache = LocalAccessCache(static_key=STATIC_KEY, dynamic_key=DYNAMIC_KEY)
    cache.update({"id": [{"type": "cardid_h", "quantity": 1, "list": [other_cardid_h]}]})

    allowed, user_id = cache.is_allowed("cardid_partial_h", str(card_data))

    assert allowed is False
    assert user_id is None


def test_old_full_hash_scheme_would_not_match():
    """Регрессионный тест: старая (ошибочная) схема - применение полного
    hash_identifier() к уже частично хешированному card_data - НЕ должна
    совпадать с корректно посчитанным cardid_h. Это подтверждает, что баг,
    который мы исправили, был реальным."""
    from app.infrastructure.cache.identifier_hash import hash_identifier

    card_data = _reader_side_partial_hash(PAN, STATIC_KEY)
    correct_cardid_h = _backend_side_cardid_h(PAN, STATIC_KEY, DYNAMIC_KEY)

    wrong_hash = hash_identifier(str(card_data), STATIC_KEY, DYNAMIC_KEY)

    assert wrong_hash != correct_cardid_h
