"""
Сервис обновления ключей QR/карт «МИР» (п. 5.4.2 ТЗ).

Раз в сутки запрашивает у бэкенда актуальные наборы ключей (ресурс
``keys/get``) и передаёт их в ``QRDecoder`` для хранения в оперативной
памяти.  Ничего не пишется на SD-карту (согласно ТЗ).

Классы
-------
- KeySyncService: периодическое обновление ключей QR/карт.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    CRYPTOGRAPHY_AVAILABLE = True
except ImportError:
    CRYPTOGRAPHY_AVAILABLE = False

if TYPE_CHECKING:
    from app.infrastructure.firmware.serial.qr_decoder import QRDecoder


class KeySyncService:
    """Периодически синхронизирует ключи QR/карт «МИР» с бэкендом.

    Все ключи хранятся только в оперативной памяти.
    """

    def __init__(
        self,
        backend,
        qr_decoder: QRDecoder | None = None,
        sync_interval_s: float = 86400.0,
    ):
        if not CRYPTOGRAPHY_AVAILABLE:
            raise ImportError("Модуль cryptography не установлен. Установите: pip install cryptography")
        self._backend = backend
        self._qr_decoder = qr_decoder
        self._sync_interval = sync_interval_s
        # -inf гарантирует, что первый tick() всегда синхронизируется сразу
        # после старта, а не ждёт полного интервала (аналогично §5.4.2:
        # ключи нужны с самого начала работы контроллера).
        self._last_sync = float("-inf")
        # Множество актуальных key-id для вычистки неактуальных
        self._known_nums: set[int] = set()

    def tick(self, now: float) -> None:
        if now - self._last_sync >= self._sync_interval:
            self._sync()
            self._last_sync = now

    def force_sync(self) -> None:
        """Синхронизировать немедленно при следующем tick()."""
        self._last_sync = float("-inf")

    def _sync(self) -> None:
        try:
            keys = self._backend.get_keys()
        except Exception:
            logger.exception("KeySyncService: не удалось получить набор ключей")
            return

        if not keys:
            logger.warning("KeySyncService: бэкенд вернул пустой список ключей")
            return

        received_nums: set[int] = set()
        for entry in keys:
            num = entry.get("num")
            if num is None:
                continue
            received_nums.add(num)
            self._load_key_set(num, entry)

        # Удалить из памяти наборы, которых больше нет в ответе бэкенда
        for old_num in self._known_nums - received_nums:
            if self._qr_decoder is not None:
                self._qr_decoder.remove_keys(old_num)

        self._known_nums = received_nums
        logger.info("KeySyncService: обновлено %d наборов ключей", len(received_nums))

    def _load_key_set(self, num: int, entry: dict) -> None:
        """Разобрать ключи из ответа бэкенда и передать в QRDecoder."""
        public_hex = entry.get("public")
        shared_hex = entry.get("shared")

        if not public_hex or not shared_hex:
            logger.warning("KeySyncService: набор %d неполный (нет public/shared), пропускаем", num)
            return

        public_bytes = bytes.fromhex(public_hex)
        public_key = Ed25519PublicKey.from_public_bytes(public_bytes)
        shared_key = bytes.fromhex(shared_hex)

        if self._qr_decoder is not None:
            self._qr_decoder.set_keys(num, public_key, shared_key)
