"""
Общие обработчики для учётных данных.

Содержит общую логику обработки карт и QR-кодов для соблюдения DRY.
"""
from scud_lgtu.domain.models import AuthSession
from scud_lgtu.domain.enums import DirectionEnum
import logging
import asyncio

logger = logging.getLogger(__name__)


async def handle_credential_common(event, turnstile, access_policy, passage_tracker, event_bus, session, reader: str = "w1") -> None:
    """
    Общий обработчик для учётных данных (карты и QR-коды).

    Parameters
    ----------
    event : CardRead or QrRead
        Событие считывания учётных данных
    turnstile : TurnstileState
        Состояние турникета для управления
    access_policy : AccessPolicy
        Политика доступа для проверки разрешений
    passage_tracker : PassageTracker
        Трекер проходов для предотвращения двойных проходов
    event_bus : EventBus
        Шина событий для публикации команд
    session : AuthSession
        Сессия авторизации с токеном
    reader : str, optional
        Имя считывателя (по умолчанию "w1")
    """
    logger.info(f"Обработка события учётных данных: {event}")

    # Проверка доступа
    decision = access_policy.check(event.credential)
    logger.info(f"Результат проверки доступа: {decision}")

    if decision.allowed:
        # Обновляем user_id в сессии
        session.user_id = decision.user_id

        # Отслеживание прохода
        passage_tracker.track(session)

        # Открытие турникета через background task (таймер запускается сразу)
        asyncio.create_task(turnstile.open_entry_async(event_bus, start_timer=True))
        logger.info(f"Открытие турникета через async task")

        # Включить зеленый индикатор на configured duration
        asyncio.create_task(turnstile.set_indicator_async(event_bus, f"{reader}_green", True, turnstile._indicator_duration))
    else:
        # Отказ в доступе - последовательность писков через background task
        asyncio.create_task(turnstile.deny_beep_sequence(event_bus))
        logger.info(f"Отказ в доступе, запущена последовательность писков")

        # Включить красный индикатор на configured duration
        asyncio.create_task(turnstile.set_indicator_async(event_bus, f"{reader}_red", True, turnstile._indicator_duration))
