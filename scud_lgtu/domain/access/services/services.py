"""
Доменные сервисы системы СКУД.

Этот модуль определяет сервисы бизнес-логики для работы с доступом и проходами:
- AccessPolicy: политика доступа для проверки учётных данных
- PassageTracker: отслеживание проходов для предотвращения двойных проходов
- CredentialHasher: хеширование учётных данных для сравнения

Классы
-------
- AccessPolicy: проверяет учётные данные через кэш доступа и возвращает решение о доступе
- PassageTracker: отслеживает сессии проходов для предотвращения повторного входа с тем же токеном
- CredentialHasher: хеширует учётные данные с использованием статического и динамического ключей
"""
from typing import Tuple, Optional
from scud_lgtu.domain.common.models.models import Credential, AccessDecision, AuthSession
from scud_lgtu.domain.common.enums.enums import TokenTypeEnum, DirectionEnum


class AccessPolicy:
    """
    Политика доступа для проверки учётных данных.
    
    Использует кэш доступа для проверки разрешений на основе учётных данных.
    """
    
    def __init__(self, cache=None):
        """
        Инициализировать политику доступа с кэшем.

        Parameters
        ----------
        cache : AccessCache, optional
            Кэш доступа для проверки разрешений. Если None, доступ всегда запрещен.
        """
        self._cache = cache
    
    def check(self, credential: Credential) -> AccessDecision:
        """
        Проверить, разрешены ли учётные данные.

        Parameters
        ----------
        credential : Credential
            Учётные данные для проверки (карта, QR-код и т.д.)

        Returns
        -------
        AccessDecision
            Решение о доступе (разрешено/запрещено) с причиной и user_id
        """
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
    """
    Отслеживание проходов для предотвращения двойных проходов.
    
    Хранит информацию о последних проходах для каждого токена (карты/QR-кода).
    Предотвращает повторный вход с тем же токеном до завершения прохода.
    """
    
    def __init__(self):
        """Инициализировать отслеживание проходов."""
        # Формат: {token: {"direction": "in"/"out", "passed": bool}}
        self._last_passages = {}
    
    def track(self, session: AuthSession) -> None:
        """
        Отследить новую сессию прохода.

        Parameters
        ----------
        session : AuthSession
            Сессия авторизации для отслеживания
        """
        self._last_passages[session.token] = {
            "direction": session.direction.value,
            "passed": session.used
        }
    
    def is_double_pass(self, token: str, direction: DirectionEnum) -> bool:
        """
        Проверить, является ли это двойным проходом.

        Parameters
        ----------
        token : str
            Токен учётных данных
        direction : DirectionEnum
            Направление прохода

        Returns
        -------
        bool
            True если это двойной проход в том же направлении, False иначе
        """
        if token not in self._last_passages:
            return False
        
        last_passage = self._last_passages[token]
        
        # Двойной проход если направление совпадает и предыдущий проход завершен
        if last_passage["direction"] == direction.value and last_passage["passed"]:
            return True
        
        return False
    
    def mark_completed(self, token: str) -> None:
        """
        Отметить проход как завершённый.

        Parameters
        ----------
        token : str
            Токен учётных данных
        """
        if token in self._last_passages:
            self._last_passages[token]["passed"] = True
    
    def mark_passed(self, token: str) -> None:
        """
        Отметить проход как завершённый (синоним mark_completed).

        Parameters
        ----------
        token : str
            Токен учётных данных
        """
        self.mark_completed(token)


class CredentialHasher:
    """
    Хеширование учётных данных для сравнения.
    
    Использует HMAC-SHA256 для безопасного хеширования учётных данных
    с использованием статического и динамического ключей.
    """
    
    @staticmethod
    def hash(value: str, static_key: str, dynamic_key: str) -> str:
        """
        Хешировать значение учётных данных.

        Parameters
        ----------
        value : str
            Исходное значение учётных данных
        static_key : str
            Статический ключ (уникален для точки доступа)
        dynamic_key : str
            Динамический ключ (меняется ежедневно)

        Returns
        -------
        str
            Хешированное значение

        Note
        ----
        Реализация в identifier_hash.py.
        Алгоритм: HMAC_SHA256(HMAC_SHA256(SHA256(value), STATIC_KEY), DYNAMIC_KEY)
        """
        # Заглушка - реальная реализация в identifier_hash.py
        return value
