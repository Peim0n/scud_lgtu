"""Обработчик событий прохода."""
from scud_lgtu.domain.events import PassageDetected
from scud_lgtu.domain.events import OutputCommandsGenerated
import logging
import asyncio

logger = logging.getLogger(__name__)


async def handle_passage_detected(event: PassageDetected, turnstile, passage_tracker, event_bus, event_log) -> None:
    """Обработать событие обнаружения прохода."""
    direction = event.direction
    zone = event.zone
    duration = event.duration
    
    logger.info(f"Проход: {zone}, направление={direction}, длительность={duration:.3f}s")
    
    if direction == "blockage":
        # Заслон - держать реле открытым
        logger.warning(f"Заслон: {zone}, длительность={duration:.3f}s")
        
        # Логировать заслон
        event_log.log_passage(zone, "blockage", duration, result="blockage")
        
        # Держать реле открытым (не закрывать)
        # Реле уже открыто при проходе, просто не закрываем его
        return
    
    if direction == "turnback":
        # Разворот - закрыть реле
        logger.info(f"Разворот: {zone}, длительность={duration:.3f}s")
        
        # Логировать разворот
        event_log.log_passage(zone, "turnback", duration, result="turnback")
        
        # Закрыть реле
        await turnstile.close_async(event_bus)
        return
    
    # Нормальный проход (in/out)
    # Закрыть реле
    await turnstile.close_async(event_bus)
    
    # Логировать проход
    event_log.log_passage(zone, direction, duration, result="pass")
    
    # Отметить проход как завершённый в passage_tracker
    # Это позволит снова зайти с той же картой (но только если направление изменилось)
    if event.token:
        passage_tracker.mark_passed(event.token)
