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
from time import time

from app.domain.enums import (
    DirectionEnum,
    ResultEnum,
    SeverityEnum,
    TokenTypeEnum,
)


@dataclass
class Credential:
    token_type: TokenTypeEnum
    value: str
    encrypted: bool = False


@dataclass
class AccessDecision:
    allowed: bool
    user_id: int | None = None
    reason: str = ""


@dataclass
class AuthSession:
    token: str
    direction: DirectionEnum
    created_at: float = field(default_factory=time)
    used: bool = False
    user_id: int | None = None

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
    token: str | None = None
    user_id: int | None = None
    token_type: str | None = None
    """Тип идентификатора для журнала событий (п. 5.5 ТЗ): phone | phone_h |
    maxid | maxid_h | cardid | cardid_h. Внутренние типы (например,
    cardid_partial_h) должны приводиться к типу с проводного протокола
    перед записью в журнал/отправкой на бэкенд."""
    raw_input: str | None = None
    """Сырой QR URL или данные карты, которыми пытались зайти — для аудита."""
    severity: str = SeverityEnum.INFO.value


@dataclass
class OutputCommand:
    name: str
    state: bool
    duration: float | None = None
