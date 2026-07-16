"""Обработчик событий карт."""
from scud_lgtu.domain.events import CardRead
from scud_lgtu.domain.models import AuthSession
from scud_lgtu.domain.enums import DirectionEnum, TokenTypeEnum
import logging

logger = logging.getLogger(__name__)


def handle_card_read(event: CardRead, turnstile, access_policy, passage_tracker) -> None:
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
        
        # Открытие турникета
        commands = turnstile.open_entry()
        logger.info(f"Команды открытия турникета: {commands}")
        # Применение команд через исполнительный механизм (для реализации)
    else:
        # Отказ в доступе
        commands = turnstile.block()
        logger.info(f"Команды блокировки: {commands}")
        # Применение команд через исполнительный механизм (для реализации)
