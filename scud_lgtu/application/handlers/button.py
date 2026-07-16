"""Обработчик событий кнопок."""
from scud_lgtu.domain.events import ButtonPressed, OutputCommandsGenerated
from scud_lgtu.domain.enums import DirectionEnum
import logging

logger = logging.getLogger(__name__)


def handle_button_pressed(event: ButtonPressed, turnstile, event_bus) -> None:
    """Обработать событие нажатия кнопки."""
    logger.info(f"handle_button_pressed: {event}")
    
    # Кнопки работают на HIGH: 0 = покой, 1 = нажатие
    # Реагируем только на нажатие (state=True)
    if not event.state:
        logger.info(f"Button {event.button_id} released (state=False), ignoring")
        return
    
    if event.button_id == "button_1":
        # Открыть для входа
        commands = turnstile.open_entry()
        logger.info(f"button_1 open_entry commands: {commands}")
    elif event.button_id == "button_2":
        # Открыть для выхода
        commands = turnstile.open_exit()
        logger.info(f"button_2 open_exit commands: {commands}")
    elif event.button_id == "button_3":
        # Обработка кнопки 3 (может быть что-то другое)
        commands = turnstile.close()
        logger.info(f"button_3 close commands: {commands}")
    else:
        # Неизвестная кнопка - закрыть турникет
        commands = turnstile.close()
        logger.info(f"unknown button close commands: {commands}")
    
    # Публикуем событие с командами для применения
    if commands:
        commands_event = OutputCommandsGenerated(commands=commands)
        logger.info(f"Publishing OutputCommandsGenerated: {commands_event}")
        event_bus.publish(commands_event)
