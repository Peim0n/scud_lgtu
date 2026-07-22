"""
Обработчик событий кнопок системы СКУД.

Поддерживает:
- обычные кнопки входа/выхода (разовое открытие);
- кнопку Shift (button_3) для перехода в разблокированные режимы;
- короткое нажатие Shift для закрытия.
"""
from time import time
from scud_lgtu.domain.common.events.events import ButtonPressed, OutputCommandsGenerated
from scud_lgtu.domain.turnstile.services.turnstile import TurnstileStateEnum
import logging

logger = logging.getLogger(__name__)


# Состояние Shift-кнопки между событиями нажатия/отжатия
_shift_state = {"pressed": False, "used": False, "press_time": 0.0}


def _find_button_config(devices: dict, button_id: str):
    buttons = devices.get("buttons", {})
    for button_cfg in buttons.values():
        if button_cfg.get("label") == button_id:
            return button_cfg
    return None


def handle_button_pressed(event: ButtonPressed, turnstile, event_bus, devices: dict) -> None:
    """Обработать событие нажатия/отжатия кнопки через TurnstileState."""
    global _shift_state
    logger.info(f"Button event: button_id={event.button_id}, state={event.state}")

    button_config = _find_button_config(devices, event.button_id)
    if not button_config:
        logger.debug(f"Кнопка не найдена в конфиге: {event.button_id}")
        return

    action = button_config.get("action")
    if not action:
        logger.error(f"Кнопка {event.button_id} не имеет action")
        return

    is_pressed = event.state

    if action == "shift":
        if is_pressed:
            _shift_state["pressed"] = True
            _shift_state["used"] = False
            _shift_state["press_time"] = time()
            logger.info(f"Кнопка {event.button_id}: Shift нажат")
        else:
            if _shift_state["pressed"] and not _shift_state["used"]:
                duration = time() - _shift_state["press_time"]
                if duration <= turnstile.shift_short_press_max:
                    commands = turnstile.close()
                    if commands:
                        event_bus.publish(OutputCommandsGenerated(commands=commands))
                        logger.info(f"Кнопка {event.button_id}: короткий Shift — закрытие")
            _shift_state["pressed"] = False
            _shift_state["used"] = False
        return

    if is_pressed:
        commands = _handle_button_press(action, turnstile)
        if commands:
            event_bus.publish(OutputCommandsGenerated(commands=commands))
    elif action in ("open_entry", "open_exit"):
        turnstile.start_open_timer()
        logger.info(f"Кнопка {event.button_id}: отжатие, запущен таймер закрытия")


def _handle_button_press(action: str, turnstile) -> list:
    """Выбрать команду для нажатия кнопки с учётом Shift и текущего состояния."""
    from scud_lgtu.domain.common.events.events import OutputCommandsGenerated

    global _shift_state
    state = turnstile.current_state

    if _shift_state["pressed"]:
        _shift_state["used"] = True
        if action == "open_entry":
            logger.info("Shift + кнопка входа: разблокирован на вход")
            return turnstile.unlock_entry()
        elif action == "open_exit":
            logger.info("Shift + кнопка выхода: разблокирован на выход")
            return turnstile.unlock_exit()
        return []

    if action == "open_entry":
        if state == TurnstileStateEnum.UNLOCKED_EXIT:
            logger.info("Кнопка входа в режиме разблокированного выхода: закрытие")
            return turnstile.close()
        logger.info("Кнопка входа: открытие входа")
        return turnstile.open_entry(start_timer=False)

    if action == "open_exit":
        if state == TurnstileStateEnum.UNLOCKED_ENTRY:
            logger.info("Кнопка выхода в режиме разблокированного входа: закрытие")
            return turnstile.close()
        logger.info("Кнопка выхода: открытие выхода")
        return turnstile.open_exit(start_timer=False)

    if action == "close":
        logger.info("Кнопка закрытия")
        return turnstile.close()

    logger.error(f"Неизвестное действие кнопки: {action}")
    return []
