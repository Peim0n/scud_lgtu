"""Обработчик событий кнопок."""
from scud_lgtu.domain.events import ButtonPressed, OutputCommandsGenerated
from scud_lgtu.domain.enums import DirectionEnum
import logging

logger = logging.getLogger(__name__)


def handle_button_pressed(event: ButtonPressed, turnstile, event_bus) -> None:
    """Обработать событие нажатия кнопки."""
    logger.info(f"handle_button_pressed: {event}")
    
    # Кнопки работают на LOW: 1 = покой, 0 = нажатие
    # При нажатии (state=False) открываем турникет
    # При отжатии (state=True) запускаем таймер закрытия
    
    if event.button_id == "button_1":
        if not event.state:
            # Нажатие - открыть для входа
            commands = turnstile.open_entry()
            logger.info(f"button_1 pressed, open_entry commands: {commands}")
            if commands:
                commands_event = OutputCommandsGenerated(commands=commands)
                logger.info(f"Publishing OutputCommandsGenerated: {commands_event}")
                event_bus.publish(commands_event)
        else:
            # Отжатие - запустить таймер закрытия
            turnstile.start_open_timer()
            logger.info(f"button_1 released, started open timer")
    
    elif event.button_id == "button_2":
        if not event.state:
            # Нажатие - открыть для выхода
            commands = turnstile.open_exit()
            logger.info(f"button_2 pressed, open_exit commands: {commands}")
            if commands:
                commands_event = OutputCommandsGenerated(commands=commands)
                logger.info(f"Publishing OutputCommandsGenerated: {commands_event}")
                event_bus.publish(commands_event)
        else:
            # Отжатие - запустить таймер закрытия
            turnstile.start_open_timer()
            logger.info(f"button_2 released, started open timer")
    
    elif event.button_id == "button_3":
        if not event.state:
            # Нажатие - закрыть турникет
            commands = turnstile.close()
            logger.info(f"button_3 pressed, close commands: {commands}")
            if commands:
                commands_event = OutputCommandsGenerated(commands=commands)
                logger.info(f"Publishing OutputCommandsGenerated: {commands_event}")
                event_bus.publish(commands_event)
    
    else:
        # Неизвестная кнопка - закрыть турникет при нажатии
        if not event.state:
            commands = turnstile.close()
            logger.info(f"unknown button pressed, close commands: {commands}")
            if commands:
                commands_event = OutputCommandsGenerated(commands=commands)
                logger.info(f"Publishing OutputCommandsGenerated: {commands_event}")
                event_bus.publish(commands_event)
