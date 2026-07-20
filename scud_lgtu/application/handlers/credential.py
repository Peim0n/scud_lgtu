"""
Обработчик событий учётных данных системы СКУД.

Этот модуль реализует параметризованный обработчик событий считывания карт и QR-кодов.
Обработчик создаёт сессию авторизации с заданным префиксом токена и делегирует дальнейшую
обработку общему обработчику учётных данных, который проверяет доступ, открывает
турникет и управляет индикаторами.

Функции
-------
- handle_credential: обработать событие считывания учётных данных (карта или QR-код)
"""
from scud_lgtu.domain.common.events.events import CardRead, QrRead
from scud_lgtu.domain.common.models.models import AuthSession
from scud_lgtu.domain.common.enums.enums import DirectionEnum
from scud_lgtu.application.handlers.common import handle_credential_common
import logging
import asyncio

logger = logging.getLogger(__name__)


async def handle_credential(
    event: CardRead | QrRead,
    turnstile,
    access_policy,
    passage_tracker,
    event_bus,
    devices: dict,
    token_prefix: str = "cardid"
) -> None:
    """
    Обработать событие считывания учётных данных.

    Parameters
    ----------
    event : CardRead | QrRead
        Событие считывания карты или QR-кода
    turnstile : TurnstileState
        Состояние турникета для управления
    access_policy : AccessPolicy
        Политика доступа для проверки разрешений
    passage_tracker : PassageTracker
        Трекер проходов для предотвращения двойных проходов
    event_bus : EventBus
        Шина событий для публикации команд
    devices : dict
        Мапинг устройств из конфига
    token_prefix : str
        Префикс токена ("cardid" для карт, "maxid" для QR-кодов)
    """
    # Создание сессии авторизации с заданным префиксом
    session = AuthSession(
        token=f"{token_prefix}:{event.credential.value}",
        direction=DirectionEnum.IN,
        user_id=None  # Будет заполнено в handle_credential_common
    )

    # Используем общий обработчик для карт и QR-кодов
    await handle_credential_common(
        event=event,
        turnstile=turnstile,
        access_policy=access_policy,
        passage_tracker=passage_tracker,
        event_bus=event_bus,
        session=session,
        devices=devices
    )
