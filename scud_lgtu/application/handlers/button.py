"""
Обработчик событий кнопок системы СКУД.

Обработчик делегирует управление турникетом TurnstileState.
Конфигурация кнопок задаёт действие (open_entry, open_exit, close).
Время до закрытия после отжатия определяется TurnstileState.

Функции
-------
- handle_button_pressed: обработать событие нажатия/отжатия кнопки
"""
from scud_lgtu.domain.common.events.events import ButtonPressed, OutputCommandsGenerated
import logging

logger = logging.getLogger(__name__)


def handle_button_pressed(event: ButtonPressed, turnstile, event_bus, devices: dict) -> None:
    """Обработать событие нажатия/отжатия кнопки через TurnstileState."""
    logger.info(f"Button event: button_id={event.button_id}, state={event.state}")

    buttons = devices.get("buttons", {})

    button_config = None
    for button_cfg in buttons.values():
        if button_cfg.get("label") == event.button_id:
            button_config = button_cfg
            break

    if not button_config:
        logger.error(f"Кнопка не найдена в конфиге: {event.button_id}")
        return

    action = button_config.get("action")
    if not action:
        logger.error(f"Кнопка {event.button_id} не имеет action")
        return

    if event.state:
        commands = []
        if action == "open_entry":
            commands = turnstile.open_entry(start_timer=False)
            logger.info(f"Кнопка {event.button_id}: открытие входа")
        elif action == "open_exit":
            commands = turnstile.open_exit(start_timer=False)
            logger.info(f"Кнопка {event.button_id}: открытие выхода")
        elif action == "close":
            commands = turnstile.close()
            logger.info(f"Кнопка {event.button_id}: закрытие турникета")
        else:
            logger.error(f"Кнопка {event.button_id}: неизвестное действие {action}")
            return

        if commands:
            event_bus.publish(OutputCommandsGenerated(commands=commands))
    else:
        if action in ("open_entry", "open_exit"):
            turnstile.start_open_timer()
            logger.info(f"Кнопка {event.button_id}: отжатие, запущен таймер закрытия")
