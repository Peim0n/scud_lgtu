"""Тесты KeySyncService — обновление ключей QR/карт в памяти (п. 5.4.2 ТЗ).

Все ключи хранятся только в оперативной памяти — ничего не пишется на
SD-карту (согласно ТЗ).
"""
import os

from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from app.application.services.key_sync_service import KeySyncService


class FakeBackend:
    def __init__(self, keys, online=True):
        self._keys = keys
        self._online = online
        self.calls = 0

    def is_online(self):
        return self._online

    def get_keys(self):
        self.calls += 1
        return self._keys


class FakeQRDecoder:
    """Заглушка QRDecoder для тестов — хранит ключи в словаре."""
    def __init__(self):
        self.keys: dict[int, tuple] = {}

    def set_keys(self, key_id, public_key, shared_key):
        self.keys[key_id] = (public_key, shared_key)

    def remove_keys(self, key_id):
        self.keys.pop(key_id, None)


def _make_key_entry(num: int) -> dict:
    priv = ed25519.Ed25519PrivateKey.generate()
    pub_bytes = priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return {
        "num": num,
        "public": pub_bytes.hex(),
        "shared": os.urandom(16).hex(),
        "dynamic": os.urandom(32).hex(),
    }


def test_sync_loads_keys_into_decoder():
    entry = _make_key_entry(1)
    backend = FakeBackend([entry])
    decoder = FakeQRDecoder()
    service = KeySyncService(backend, qr_decoder=decoder, sync_interval_s=86400)

    service.tick(now=1000.0)

    assert 1 in decoder.keys
    pub_key, shared_key = decoder.keys[1]
    assert len(shared_key) == 16


def test_sync_prunes_stale_key_sets():
    decoder = FakeQRDecoder()
    backend = FakeBackend([_make_key_entry(1)])
    service = KeySyncService(backend, qr_decoder=decoder, sync_interval_s=86400)
    service.tick(now=1000.0)
    assert 1 in decoder.keys

    # Следующая синхронизация возвращает только набор 2 — набор 1 должен исчезнуть.
    backend._keys = [_make_key_entry(2)]
    service.force_sync()
    service.tick(now=2000.0)

    assert 1 not in decoder.keys
    assert 2 in decoder.keys


def test_sync_respects_interval():
    backend = FakeBackend([_make_key_entry(1)])
    service = KeySyncService(backend, sync_interval_s=86400)
    service.tick(now=1000.0)
    service.tick(now=1000.0 + 100)  # рано, интервал не истёк

    assert backend.calls == 1


def test_sync_skipped_when_backend_offline():
    decoder = FakeQRDecoder()
    backend = FakeBackend([_make_key_entry(1)], online=False)
    service = KeySyncService(backend, qr_decoder=decoder, sync_interval_s=86400)

    service.tick(now=1000.0)

    assert backend.calls == 0
    assert len(decoder.keys) == 0
