"""
Локальный кэш разрешённых идентификаторов.

Хранит списки доступа, полученные от бэкенда, для работы офлайн.
Поддерживает загрузку из JSON-файла для тестирования.
"""

import json
import logging
import os
from typing import Any, Optional, Tuple

from .identifier_hash import hash_identifier, normalize

logger = logging.getLogger(__name__)


class LocalAccessCache:
    """
    Локальный кэш разрешений.

    Пока in-memory; в production — SQLite/LevelDB.
    """

    def __init__(
        self,
        path: str | None = None,
        static_key: str | None = None,
        dynamic_key: str | None = None,
    ) -> None:
        """Загрузить кэш из JSON, если указан путь."""
        self._allowed: dict[str, set[str]] = {}
        self._user_by_token: dict[str, int] = {}
        self._users: dict[int, dict[str, str]] = {}
        self._path = path
        self._static_key = static_key
        self._dynamic_key = dynamic_key
        if path and os.path.exists(path):
            self.load_json(path)

    def _hash(self, id_type: str, value: str) -> str:
        """Хешировать идентификатор, если заданы ключи."""
        if self._static_key is None or self._dynamic_key is None:
            return value
        # В кэше бэкенда хранятся хеши вида *_h; raw типы хешируем здесь
        if id_type.endswith("_h"):
            return value
        return hash_identifier(value, self._static_key, self._dynamic_key)

    def update(self, data: dict[str, Any]) -> None:
        """Обновить кэш из ответа бэкенда."""
        self._allowed.clear()
        self._user_by_token.clear()
        self._users.clear()
        for item in data.get("id", []):
            id_type = item.get("type")
            values = set(item.get("list", []))
            if id_type:
                self._allowed[id_type] = values
        for user_id, user in data.get("users", {}).items():
            uid = int(user_id)
            self._users[uid] = {}
            for id_type, value in user.items():
                if id_type == "user_id":
                    continue
                h = self._hash(id_type, normalize(value))
                self._user_by_token[h] = uid
                self._users[uid][id_type] = value
        logger.info("LocalAccessCache обновлён: %s", {k: len(v) for k, v in self._allowed.items()})

    def is_allowed(self, id_type: str, token: str) -> Tuple[bool, Optional[int]]:
        """
        Проверить, разрешён ли идентификатор.

        Returns
        -------
        (allowed, user_id)
        """
        h = self._hash(id_type, normalize(token))
        allowed = h in self._allowed.get(id_type, set()) or h in self._allowed.get(id_type + "_h", set())
        user_id = self._user_by_token.get(h) if allowed else None
        return allowed, user_id

    def add(self, id_type: str, token: str, user_id: Optional[int] = None) -> None:
        """Добавить идентификатор вручную."""
        h = self._hash(id_type, normalize(token))
        self._allowed.setdefault(id_type, set()).add(h)
        if user_id is not None:
            uid = int(user_id)
            self._user_by_token[h] = uid
            self._users.setdefault(uid, {})[id_type] = token
        if self._path:
            self.save_json(self._path)

    def load_json(self, path: str) -> None:
        """Загрузить кэш из JSON-файла."""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self._allowed.clear()
        self._user_by_token.clear()
        self._users.clear()

        # Формат users: {"user_id": {"maxid": "...", "cardid": "..."}}
        users = data.get("users", {})
        for user_id, user in users.items():
            uid = int(user_id)
            self._users[uid] = {}
            for id_type, value in user.items():
                if id_type == "user_id":
                    continue
                h = self._hash(id_type, normalize(value))
                self._allowed.setdefault(id_type, set()).add(h)
                self._user_by_token[h] = uid
                self._users[uid][id_type] = value

        # Legacy формат: {"cardid": ["..."], "maxid": ["..."]}
        for id_type, values in data.items():
            if id_type == "users":
                continue
            self._allowed.setdefault(id_type, set()).update(
                self._hash(id_type, normalize(v)) for v in values
            )

        logger.info("LocalAccessCache загружен из %s: %s", path, {k: len(v) for k, v in self._allowed.items()})

    def save_json(self, path: str) -> None:
        """Сохранить кэш в JSON-файл."""
        with open(path, "w", encoding="utf-8") as f:
            json.dump(
                {"users": {str(k): v for k, v in self._users.items()},
                 "allowed": {k: list(v) for k, v in self._allowed.items()}},
                f,
                indent=2,
                ensure_ascii=False,
            )
