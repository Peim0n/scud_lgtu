"""
Доменные модели системы СКУД.

Этот модуль определяет основные доменные сущности, используемые в бизнес-логике:
- Credential: учётные данные для доступа (QR-код, карта и т.д.)
- AccessDecision: решение о разрешении доступа
- AuthSession: сессия авторизации для прохода
- Passage: информация о событии прохода
- OutputCommand: команда для управления выходами оборудования

Классы
-------
- Credential: учётные данные с типом токена, значением и флагом шифрования
- AccessDecision: результат проверки доступа с разрешением, user_id и причиной
- AuthSession: сессия авторизации с токеном, направлением, временем создания и статусом использования
- Passage: событие прохода с направлением, зоной, длительностью и результатом
- OutputCommand: команда для управления выходом с именем, состоянием и длительностью
"""
from dataclasses import dataclass, field
from typing import Optional
from time import time
from scud_lgtu.domain.common.enums.enums import DirectionEnum, TokenTypeEnum, ResultEnum


@dataclass
class Credential:
    token_type: TokenTypeEnum
    value: str
    encrypted: bool = False


@dataclass
class AccessDecision:
    allowed: bool
    user_id: Optional[int] = None
    reason: str = ""


@dataclass
class AuthSession:
    token: str
    direction: DirectionEnum
    created_at: float = field(default_factory=time)
    used: bool = False
    user_id: Optional[int] = None

    def is_expired(self, timeout: float) -> bool:
        return (time() - self.created_at) > timeout

    def mark_used(self) -> None:
        self.used = True


@dataclass
class Passage:
    direction: DirectionEnum
    zone: str
    duration: float
    result: ResultEnum


@dataclass
class OutputCommand:
    name: str
    state: bool
    duration: Optional[float] = None
