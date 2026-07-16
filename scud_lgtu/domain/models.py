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
from scud_lgtu.domain.enums import DirectionEnum, TokenTypeEnum, ResultEnum


@dataclass
class Credential:
    """
    Учётные данные для доступа (QR-код, карта и т.д.).

    Attributes
    ----------
    token_type : TokenTypeEnum
        Тип токена (CARD, QR, и т.д.)
    value : str
        Значение токена (номер карты, QR-код и т.д.)
    encrypted : bool, optional
        Зашифрованы ли данные (по умолчанию False)
    """
    token_type: TokenTypeEnum
    value: str
    encrypted: bool = False


@dataclass
class AccessDecision:
    """
    Решение о разрешении доступа.

    Attributes
    ----------
    allowed : bool
        Разрешен ли доступ
    user_id : int, optional
        ID пользователя если доступ разрешен
    reason : str, optional
        Причина отказа если доступ запрещен
    """
    allowed: bool
    user_id: Optional[int] = None
    reason: str = ""


@dataclass
class AuthSession:
    """
    Сессия авторизации для прохода.

    Attributes
    ----------
    token : str
        Токен учётных данных
    direction : DirectionEnum
        Направление прохода (вход/выход)
    created_at : float, optional
        Время создания сессии (Unix timestamp)
    used : bool, optional
        Использована ли сессия (по умолчанию False)
    user_id : int, optional
        ID пользователя
    """
    token: str
    direction: DirectionEnum
    created_at: float = field(default_factory=time)
    used: bool = False
    user_id: Optional[int] = None

    def is_expired(self, timeout: float) -> bool:
        """
        Проверить, истекла ли сессия авторизации.

        Parameters
        ----------
        timeout : float
            Таймаут сессии в секундах

        Returns
        -------
        bool
            True если сессия истекла, False иначе
        """
        return (time() - self.created_at) > timeout

    def mark_used(self) -> None:
        """Отметить сессию авторизации как использованную."""
        self.used = True


@dataclass
class Passage:
    """
    Информация о событии прохода.

    Attributes
    ----------
    direction : DirectionEnum
        Направление прохода (вход/выход)
    zone : str
        Зона прохода (идентификатор датчика)
    duration : float
        Длительность прохода в секундах
    result : ResultEnum
        Результат прохода (успех/отказ/разворот/заслон)
    """
    direction: DirectionEnum
    zone: str
    duration: float
    result: ResultEnum


@dataclass
class OutputCommand:
    """
    Команда для управления выходами оборудования.

    Attributes
    ----------
    name : str
        Имя выхода (например, "rel1", "w1_green", "buz")
    state : bool
        Состояние выхода (True = включено, False = выключено)
    duration : float, optional
        Длительность включения в секундах. Если None - без автовыключения
    """
    name: str
    state: bool
    duration: Optional[float] = None
