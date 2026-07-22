"""
Обработчик событий прохода системы СКУД.

При срабатывании датчика фиксирует проход и закрывает турникет.
"""
from scud_lgtu.domain.common.events.events import PassageDetected, PassageStarted, PassageSensorsCleared, OutputCommandsGenerated
from scud_lgtu.domain.common.models.models import Passage
from scud_lgtu.domain.common.enums.enums import ResultEnum, DirectionEnum
import logging

logger = logging.getLogger(__name__)


def handle_passage_detected(event: PassageDetected, turnstile, passage_tracker, event_bus, passage_service, devices: dict) -> None:
    """Обработать событие обнаружения прохода."""
    direction = event.direction
    zone = event.zone
    duration = event.duration

    logger.info(f"Проход: {zone}, направление={direction}, длительность={duration:.3f}s")

    direction_enum = DirectionEnum.IN if direction == "in" else DirectionEnum.OUT
    passage = Passage(
        direction=direction_enum,
        zone=zone,
        duration=duration,
        result=ResultEnum.PASS,
        token=event.token,
        user_id=event.user_id,
    )
    passage_service.log_passage(passage)

    commands = turnstile.close()
    if commands:
        event_bus.publish(OutputCommandsGenerated(commands=commands))


def handle_passage_started(event: PassageStarted, turnstile) -> None:
    """Обработать начало прохода (устаревшее, игнорируется)."""
    logger.debug(f"Passage started: {event.zone} direction={event.direction}")


def handle_passage_cleared(event: PassageSensorsCleared, turnstile, event_bus) -> None:
    """Обработать освобождение датчиков (устаревшее, игнорируется)."""
    logger.debug(f"Passage sensors cleared: {event.zone}")
