"""
Обработчик событий карт.

Обрабатывает события считывания карт с Wiegand-считывателей.
Проверяет доступ, открывает турникет, управляет индикаторами.
"""
from scud_lgtu.domain.events import CardRead
from scud_lgtu.domain.models import AuthSession
from scud_lgtu.domain.enums import DirectionEnum, TokenTypeEnum, AccessResultEnum
import logging
import asyncio

logger = logging.getLogger(__name__)


async def handle_card_read(event: CardRead, turnstile, access_policy, passage_tracker, event_bus) -> None:
    """
    Обработать событие считывания карты.

    Parameters
    ----------
    event : CardRead
        Событие считывания карты
    turnstile : TurnstileState
        Состояние турникета для управления
    access_policy : AccessPolicy
        Политика доступа для проверки разрешений
    passage_tracker : PassageTracker
        Трекер проходов для предотвращения двойных проходов
    event_bus : EventBus
        Шина событий для публикации команд
    """
    logger.info(f"Обработка события карты: {event}")

    # Проверка доступа
    decision = access_policy.check(event.credential)
    logger.info(f"Результат проверки доступа: {decision}")

    if decision.allowed:
        # Создание сессии авторизации
        session = AuthSession(
            token=f"cardid:{event.credential.value}",
            direction=DirectionEnum.IN,
            user_id=decision.user_id
        )

        # Отслеживание прохода
        passage_tracker.track(session)

        # Открытие турникета через background task (таймер запускается сразу для карт)
        asyncio.create_task(turnstile.open_entry_async(event_bus, start_timer=True))
        logger.info(f"Открытие турникета через async task")

        # Включить зеленый индикатор на configured duration
        asyncio.create_task(turnstile.set_indicator_async(event_bus, "w1_green", True, turnstile._indicator_duration))
    else:
        # Отказ в доступе - последовательность писков через background task
        asyncio.create_task(turnstile.deny_beep_sequence(event_bus))
        logger.info(f"Отказ в доступе, запущена последовательность писков")

        # Включить красный индикатор на configured duration
        asyncio.create_task(turnstile.set_indicator_async(event_bus, "w1_red", True, turnstile._indicator_duration))
