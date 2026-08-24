"""
Локальный кэш разрешённых идентификаторов системы СКУД.

Этот модуль реализует in-memory кэш для хранения списков доступа, полученных
от бэкенда, для работы офлайн.  Ничего не пишется на SD-карту —
все ключи и списки доступа хранятся только в оперативной памяти как объекты
Python (согласно ТЗ).

Классы
-------
- LocalAccessCache: локальный кэш разрешений

Методы LocalAccessCache
------------------------
- __init__: создать пустой кэш
- _hash: хешировать идентификатор, если заданы ключи
- update: обновить кэш из ответа бэкенда
- is_allowed: проверить, разрешён ли идентификатор
- add: добавить идентификатор вручную
"""

import logging
from typing import Any

from app.infrastructure.cache.identifier_hash import (
    hash_identifier,
    hash_partial_identifier,
    normalize,
)

logger = logging.getLogger(__name__)

# Типы идентификаторов, для которых на входе уже частично посчитан хеш
# (например, Wiegand-ридером в режиме "HMAC-SHA256(SHA256(PAN), KEY)") —
# нужен только финальный раунд HMAC(..., DYNAMIC_KEY), а не полная формула
# hash_identifier(). Значение — тип, под которым итоговый хеш нужно искать
# среди разрешённых идентификаторов, присланных бэкендом.
PARTIAL_HASH_LOOKUP_TARGET: dict[str, str] = {
    "cardid_partial_h": "cardid_h",
}


class LocalAccessCache:
    def __init__(
        self,
        static_key: str | None = None,
        dynamic_key: str | None = None,
    ) -> None:
        self._allowed: dict[str, set[str]] = {}
        self._user_by_token: dict[str, int] = {}
        self._users: dict[int, dict[str, str]] = {}
        self._static_key = static_key
        self._dynamic_key = dynamic_key

    def _hash(self, id_type: str, value: str) -> str:
        if self._static_key is None or self._dynamic_key is None:
            return value

        # Частично хешированные считывателем идентификаторы (карты Wiegand в
        # режиме HMAC-SHA256(SHA256(PAN), KEY)) — довычисляем только шаг с
        # DYNAMIC_KEY, полную формулу с SHA256+STATIC_KEY заново не гоняем.
        if id_type in PARTIAL_HASH_LOOKUP_TARGET:
            return hash_partial_identifier(value, self._dynamic_key)
        # В кэше бэкенда хранятся хеши вида *_h; raw типы хешируем здесь
        if id_type.endswith("_h"):
            return value
        # maxid и phone из QR-считывателя приходят в открытом виде —
        # бэкенд тоже отдаёт их открытыми. Хеширование (hash_identifier)
        # нужно только для PAN номеров карт (cardid).
        if id_type in ("maxid", "phone"):
            return value
        return hash_identifier(value, self._static_key, self._dynamic_key)

    def update(self, data: dict[str, Any]) -> None:
        # Ответ access/get может не содержать список id[] при update=1 без
        # изменений (§5.4.3) — в этом случае не затираем текущий кэш.
        if "id" not in data and "dynamic_key" not in data:
            return
        dynamic_key = data.get("dynamic_key")
        if dynamic_key:
            self._dynamic_key = dynamic_key
        if "id" not in data:
            return
        self._allowed.clear()
        self._user_by_token.clear()
        self._users.clear()
        for item in data["id"]:
            id_type = item.get("type")
            if not id_type:
                continue
            # Бэкенд может прислать идентификаторы как в сыром виде (тип без
            # суффикса "_h", например "phone"/"maxid" — тогда их нужно
            # хешировать здесь же, чтобы is_allowed() мог сравнивать хеш
            # токена от считывателя с хешем из кэша), так и уже хешированными
            # (тип "*_h") — self._hash() в этом случае вернёт значение как есть.
            self._allowed[id_type] = {
                self._hash(id_type, normalize(value)) for value in item.get("list", [])
            }
        for user_id, user in data.get("users", {}).items():
            try:
                uid = int(user_id)
            except (ValueError, TypeError):
                logger.warning("Некорректный user_id в ответе бэкенда: %s", user_id)
                continue
            self._users[uid] = {}
            for id_type, value in user.items():
                if id_type == "user_id":
                    continue
                h = self._hash(id_type, normalize(value))
                self._user_by_token[h] = uid
                self._users[uid][id_type] = value
        logger.info("LocalAccessCache обновлён: %s", {k: len(v) for k, v in self._allowed.items()})

    def is_allowed(self, id_type: str, token: str) -> tuple[bool, int | None]:
        # Значение может быть уже частично хешировано считывателем (int/decimal
        # строка от Wiegand) — normalize() тут не подходит, т.к. предназначен
        # для строковых идентификаторов вида телефона/MaxID.
        raw_value = token if id_type in PARTIAL_HASH_LOOKUP_TARGET else normalize(token)
        h = self._hash(id_type, raw_value)
        lookup_type = PARTIAL_HASH_LOOKUP_TARGET.get(id_type, id_type)
        allowed = h in self._allowed.get(lookup_type, set())
        if not allowed and not lookup_type.endswith("_h"):
            allowed = h in self._allowed.get(lookup_type + "_h", set())
        user_id = self._user_by_token.get(h) if allowed else None
        return allowed, user_id

    def add(self, id_type: str, token: str, user_id: int | None = None) -> None:
        h = self._hash(id_type, normalize(token))
        self._allowed.setdefault(id_type, set()).add(h)
        if user_id is not None:
            uid = int(user_id)
            self._user_by_token[h] = uid
            self._users.setdefault(uid, {})[id_type] = token
