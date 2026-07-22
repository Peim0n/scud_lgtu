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

logger = logging.getLogger(__name__)


def handle_credential(
    event: CardRead | QrRead,
    turnstile,
    access_policy,
    passage_tracker,
    event_bus,
    devices: dict,
    token_prefix: str = "cardid"
) -> None:
    """Обработать событие считывания учётных данных."""
    session = AuthSession(
        token=f"{token_prefix}:{event.credential.value}",
        direction=DirectionEnum.IN,
        user_id=None,
    )
    handle_credential_common(
        event=event,
        turnstile=turnstile,
        access_policy=access_policy,
        passage_tracker=passage_tracker,
        event_bus=event_bus,
        session=session,
        devices=devices,
    )
