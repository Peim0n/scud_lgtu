"""Адаптер репозитория кэша."""
from scud_lgtu.infrastructure.cache.access_cache import LocalAccessCache
from scud_lgtu.domain.models import Credential, AccessDecision


class AccessRepositoryAdapter:
    """Адаптер LocalAccessCache для реализации AccessRepository."""

    def __init__(self, cache: LocalAccessCache):
        """Инициализировать адаптер с кэшем."""
        self._cache = cache

    def is_allowed(self, credential: Credential) -> AccessDecision:
        """Проверить, разрешена ли учётная запись."""
        allowed, user_id = self._cache.is_allowed(
            credential.token_type.value,
            credential.value
        )

        if allowed:
            return AccessDecision(allowed=True, user_id=user_id)
        else:
            return AccessDecision(allowed=False, reason="Credential not in cache")

    def update(self, data: dict) -> None:
        """Обновить разрешённые идентификаторы из данных бэкенда."""
        self._cache.update(data)
