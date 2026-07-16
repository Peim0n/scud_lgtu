"""Обработчик событий QR-кодов."""
from scud_lgtu.domain.events import QrRead
from scud_lgtu.domain.models import AuthSession
from scud_lgtu.domain.enums import DirectionEnum, TokenTypeEnum
import logging

logger = logging.getLogger(__name__)


def handle_qr_read(event: QrRead, turnstile, access_policy, passage_tracker, event_bus) -> None:
    """Обработать событие считывания QR-кода."""
    logger.info(f"Обработка события QR-кода: {event}")
    
    # Проверка доступа
    decision = access_policy.check(event.credential)
    logger.info(f"Результат проверки доступа: {decision}")
    
    if decision.allowed:
        # Создание сессии авторизации
        session = AuthSession(
            token=f"maxid:{event.credential.value}",
            direction=DirectionEnum.IN,
            user_id=decision.user_id
        )
        
        # Отслеживание прохода
        passage_tracker.track(session)
        
        # Открытие турникета
        commands = turnstile.open_entry()
        logger.info(f"Команды открытия турникета: {commands}")
        if commands:
            from scud_lgtu.domain.events import OutputCommandsGenerated
            event_bus.publish(OutputCommandsGenerated(commands=commands))
    else:
        # Отказ в доступе - 3 коротких писка
        turnstile.start_deny_beep()
        logger.info(f"Отказ в доступе, запущена последовательность писков")
