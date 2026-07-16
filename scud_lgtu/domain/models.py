"""Доменные модели."""
from dataclasses import dataclass, field
from typing import Optional
from time import time
from scud_lgtu.domain.enums import DirectionEnum, TokenTypeEnum, ResultEnum


@dataclass
class Credential:
    """Учётные данные для доступа (QR-код, карта и т.д.)."""
    token_type: TokenTypeEnum
    value: str
    encrypted: bool = False


@dataclass
class AccessDecision:
    """Решение о разрешении доступа."""
    allowed: bool
    user_id: Optional[int] = None
    reason: str = ""


@dataclass
class AuthSession:
    """Сессия авторизации для прохода."""
    token: str
    direction: DirectionEnum
    created_at: float = field(default_factory=time)
    used: bool = False
    user_id: Optional[int] = None

    def is_expired(self, timeout: float) -> bool:
        """Проверить, истекла ли сессия авторизации."""
        return (time() - self.created_at) > timeout

    def mark_used(self) -> None:
        """Отметить сессию авторизации как использованную."""
        self.used = True


@dataclass
class Passage:
    """Информация о событии прохода."""
    direction: DirectionEnum
    zone: str
    duration: float
    result: ResultEnum


@dataclass
class OutputCommand:
    """Команда для управления выходами оборудования."""
    name: str
    state: bool
    duration: Optional[float] = None
