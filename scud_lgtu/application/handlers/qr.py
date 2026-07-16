"""
Обработчик событий QR-кодов.

Обрабатывает события считывания QR-кодов с QR-считывателей.
Проверяет доступ, открывает турникет, управляет индикаторами.
"""
from scud_lgtu.domain.events import QrRead
from scud_lgtu.domain.models import AuthSession
from scud_lgtu.domain.enums import DirectionEnum, TokenTypeEnum
from scud_lgtu.application.handlers.common import handle_credential_common
import logging
import asyncio

logger = logging.getLogger(__name__)


async def handle_qr_read(event: QrRead, turnstile, access_policy, passage_tracker, event_bus, devices: dict) -> None:
    """
    Обработать событие считывания QR-кода.

    Parameters
    ----------
    event : QrRead
        Событие считывания QR-кода
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
    """
    # Создание сессии авторизации с префиксом maxid
    session = AuthSession(
        token=f"maxid:{event.credential.value}",
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
