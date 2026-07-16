"""Доменные сервисы."""
from typing import Tuple, Optional
from scud_lgtu.domain.models import Credential, AccessDecision, AuthSession
from scud_lgtu.domain.enums import TokenTypeEnum, DirectionEnum


class AccessPolicy:
    """Политика доступа для проверки учётных данных."""
    
    def __init__(self, cache=None):
        """Инициализировать политику доступа с кэшем."""
        self._cache = cache
    
    def check(self, credential: Credential) -> AccessDecision:
        """Проверить, разрешены ли учётные данные."""
        if self._cache is None:
            return AccessDecision(allowed=False, reason="No cache configured")
        
        # Делегировать проверку кэшу
        allowed, user_id = self._cache.is_allowed(
            credential.token_type.value,
            credential.value
        )
        
        if allowed:
            return AccessDecision(allowed=True, user_id=user_id)
        else:
            return AccessDecision(allowed=False, reason="Credential not in cache")


class PassageTracker:
    """Отслеживание проходов для предотвращения двойных проходов."""
    
    def __init__(self):
        """Инициализировать отслеживание проходов."""
        self._last_passages = {}  # {token: {"direction": "in"/"out", "passed": bool}}
    
    def track(self, session: AuthSession) -> None:
        """Отследить новую сессию прохода."""
        self._last_passages[session.token] = {
            "direction": session.direction.value,
            "passed": session.used
        }
    
    def is_double_pass(self, token: str, direction: DirectionEnum) -> bool:
        """Проверить, является ли это двойным проходом."""
        if token not in self._last_passages:
            return False
        
        last_passage = self._last_passages[token]
        
        if last_passage["direction"] == direction.value and last_passage["passed"]:
            return True
        
        return False
    
    def mark_completed(self, token: str) -> None:
        """Отметить проход как завершённый."""
        if token in self._last_passages:
            self._last_passages[token]["passed"] = True


class CredentialHasher:
    """Хеширование учётных данных для сравнения."""
    
    @staticmethod
    def hash(value: str, static_key: str, dynamic_key: str) -> str:
        """Хешировать значение учётных данных."""
        # Заглушка - реальная реализация в identifier_hash.py
        # HMAC_SHA256(HMAC_SHA256(SHA256(value), STATIC_KEY), DYNAMIC_KEY)
        return value
