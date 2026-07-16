"""Обработчик событий карт."""
from scud_lgtu.domain.events import CardRead
from scud_lgtu.domain.models import AuthSession
from scud_lgtu.domain.enums import DirectionEnum, TokenTypeEnum
import logging
import asyncio

logger = logging.getLogger(__name__)


async def handle_card_read(event: CardRead, turnstile, access_policy, passage_tracker, event_bus) -> None:
    """Обработать событие считывания карты."""
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
    else:
        # Отказ в доступе - 3 коротких писка через background task
        asyncio.create_task(turnstile.deny_beep_sequence(event_bus))
        logger.info(f"Отказ в доступе, запущена последовательность писков")
