"""
Обработчик событий кнопок системы СКУД.

Этот модуль реализует обработчик событий нажатия кнопок управления турникетом.
Кнопки работают на LOW: 1 = покой, 0 = нажатие. При нажатии (state=False) открываем
турникет и обновляем таймер закрытия на 2 секунды. Обработчик использует
конфигурацию устройств для динамического определения реле и времени открытия.

Функции
-------
- handle_button_pressed: обработать событие нажатия кнопки
"""
from scud_lgtu.domain.common.events.events import ButtonPressed, OutputCommandsGenerated, OutputCommand
from scud_lgtu.infrastructure.persistence.event_store import CommandAction
import logging
import time
import threading

logger = logging.getLogger(__name__)

# Глобальный словарь для хранения таймеров закрытия кнопок
_button_timers = {}
_button_locks = threading.Lock()


def _schedule_close(button_id: str, relay_name: str, duration: float, event_bus) -> None:
    """Запланировать закрытие реле через указанное время."""
    def close_relay():
        commands = [OutputCommand(name=relay_name, state=False)]
        commands_event = OutputCommandsGenerated(commands=commands)
        event_bus.publish(commands_event)
        logger.info(f"Кнопка {button_id}: реле {relay_name} закрыто по таймеру")
        with _button_locks:
            if button_id in _button_timers:
                del _button_timers[button_id]

    with _button_locks:
        # Отменяем предыдущий таймер если есть
        if button_id in _button_timers:
            _button_timers[button_id].cancel()

        # Создаем новый таймер
        timer = threading.Timer(duration, close_relay)
        _button_timers[button_id] = timer
        timer.start()
        logger.debug(f"Кнопка {button_id}: таймер закрытия {relay_name} на {duration}с запущен")


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
    При нажатии (state=False) открываем реле и обновляем таймер на 2 секунды.
    Пока кнопка нажата, таймер постоянно обновляется.
    """
    logger.debug(f"handle_button_pressed: {event}")

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

    relay_name = button_config.get("relay")
    open_duration = button_config.get("open_duration", 2.0)

    if not relay_name:
        logger.error(f"Кнопка {event.button_id} не имеет конфигурации реле")
        return

    if not event.state:
        # Нажатие (state=False) - открываем реле и обновляем таймер
        commands = [OutputCommand(name=relay_name, state=True)]
        commands_event = OutputCommandsGenerated(commands=commands)
        event_bus.publish(commands_event)
        logger.info(f"Кнопка {event.button_id}: реле {relay_name} открыто")

        # Запускаем/обновляем таймер закрытия
        _schedule_close(event.button_id, relay_name, open_duration, event_bus)
    else:
        # Отжатие (state=True) - ничего не делаем, таймер продолжит работать
        logger.debug(f"Кнопка {event.button_id}: отжата, таймер продолжает работу")
