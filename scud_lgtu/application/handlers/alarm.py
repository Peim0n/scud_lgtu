"""Обработчик событий тревоги."""
from scud_lgtu.domain.events import AlarmChanged, OutputCommandsGenerated
import logging

logger = logging.getLogger(__name__)


def handle_alarm_changed(event: AlarmChanged, turnstile, event_bus) -> None:
    """Обработать событие изменения тревоги."""
    if event.active:
        commands = turnstile.set_alarm()
        logger.info(f"Alarm activated, commands: {commands}")
    else:
        commands = turnstile.clear_alarm()
        logger.info(f"Alarm cleared, commands: {commands}")
    
    # Публикуем команды через event_bus
    if commands:
        commands_event = OutputCommandsGenerated(commands=commands)
        event_bus.publish(commands_event)
