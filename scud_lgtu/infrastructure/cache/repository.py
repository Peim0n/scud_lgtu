"""Адаптер репозитория кэша."""
from scud_lgtu.infrastructure.cache.access_cache import LocalAccessCache
from scud_lgtu.domain.ports import AccessRepository
from scud_lgtu.domain.models import Credential, AccessDecision


class AccessRepositoryAdapter:
    """Adapter for LocalAccessCache to implement AccessRepository."""
    
    def __init__(self, cache: LocalAccessCache):
        """Initialize adapter with cache."""
        self._cache = cache
    
    def is_allowed(self, credential: Credential) -> AccessDecision:
        """Check if credential is allowed."""
        allowed, user_id = self._cache.is_allowed(
            credential.token_type.value,
            credential.value
        )
        
        if allowed:
            return AccessDecision(allowed=True, user_id=user_id)
        else:
            return AccessDecision(allowed=False, reason="Credential not in cache")
