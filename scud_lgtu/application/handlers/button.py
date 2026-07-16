"""
Обработчик событий кнопок.

Обрабатывает события нажатия кнопок управления турникетом.
Кнопки работают на LOW: 1 = покой, 0 = нажатие.
"""
from scud_lgtu.domain.events import ButtonPressed, OutputCommandsGenerated
from scud_lgtu.domain.enums import DirectionEnum
import logging

logger = logging.getLogger(__name__)


def handle_button_pressed(event: ButtonPressed, turnstile, event_bus, devices: dict) -> None:
    """
    Обработать событие нажатия кнопки.

    Parameters
    ----------
    event : ButtonPressed
        Событие нажатия кнопки
    turnstile : TurnstileState
        Состояние турникета для управления
    event_bus : EventBus
        Шина событий для публикации команд
    devices : dict
        Мапинг устройств из конфига

    Note
    ----
    Кнопки работают на LOW: 1 = покой, 0 = нажатие.
    При нажатии (state=False) открываем турникет.
    При отжатии (state=True) запускаем таймер закрытия.
    """
    logger.info(f"handle_button_pressed: {event}")

    # Кнопки работают на LOW: 1 = покой, 0 = нажатие
    # При нажатии (state=False) открываем турникет
    # При отжатии (state=True) запускаем таймер закрытия

    # Получаем конфигурацию кнопок из devices
    buttons = devices.get("buttons", {})

    # Находим конфигурацию кнопки по label
    button_config = None
    for button_name, button_cfg in buttons.items():
        if button_cfg.get("label") == event.button_id:
            button_config = button_cfg
            break

    if not button_config:
        logger.error(f"Кнопка не найдена в конфиге: {event.button_id}")
        return

    action = button_config.get("action", "close")

    if not event.state:
        # Нажатие - выполнить действие
        if action == "open_entry":
            commands = turnstile.open_entry()
            logger.info(f"{event.button_id} pressed, open_entry commands: {commands}")
        elif action == "open_exit":
            commands = turnstile.open_exit()
            logger.info(f"{event.button_id} pressed, open_exit commands: {commands}")
        else:  # close
            commands = turnstile.close()
            logger.info(f"{event.button_id} pressed, close commands: {commands}")

        if commands:
            commands_event = OutputCommandsGenerated(commands=commands)
            logger.info(f"Publishing OutputCommandsGenerated: {commands_event}")
            event_bus.publish(commands_event)
    else:
        # Отжатие - запустить таймер закрытия (только для open_entry и open_exit)
        if action in ("open_entry", "open_exit"):
            turnstile.start_open_timer()
            logger.info(f"{event.button_id} released, started open timer")
