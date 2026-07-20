"""
Обработчик событий кнопок системы СКУД.

Этот модуль реализует обработчик событий нажатия кнопок управления турникетом.
Кнопки работают на LOW: 1 = покой, 0 = нажатие. При нажатии (state=False) открываем
турникет и обновляем таймер закрытия на 2 секунды. Обработчик использует
конфигурацию устройств для динамического определения реле и времени открытия.

Классы
-------
- ButtonHandler: обработчик событий кнопок с хранением состояния таймеров
"""
from scud_lgtu.domain.common.events.events import ButtonPressed, OutputCommandsGenerated, OutputCommand
import logging
import time
import threading

logger = logging.getLogger(__name__)


class ButtonHandler:
    """Обработчик событий кнопок с хранением состояния таймеров."""
    
    def __init__(self):
        self._button_timers = {}
        self._button_locks = threading.Lock()
    
    def handle(self, event: ButtonPressed, turnstile, event_bus, devices: dict) -> None:
        """Обработать событие нажатия кнопки."""
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
            self._schedule_close(event.button_id, relay_name, open_duration, event_bus)
        else:
            # Отжатие (state=True) - ничего не делаем, таймер продолжит работать
            logger.debug(f"Кнопка {event.button_id}: отжата, таймер продолжает работу")
    
    def _schedule_close(self, button_id: str, relay_name: str, duration: float, event_bus) -> None:
        """Запланировать закрытие реле через указанное время."""
        def close_relay():
            commands = [OutputCommand(name=relay_name, state=False)]
            commands_event = OutputCommandsGenerated(commands=commands)
            event_bus.publish(commands_event)
            logger.info(f"Кнопка {button_id}: реле {relay_name} закрыто по таймеру")
            with self._button_locks:
                if button_id in self._button_timers:
                    del self._button_timers[button_id]

        with self._button_locks:
            # Отменяем предыдущий таймер если есть
            if button_id in self._button_timers:
                self._button_timers[button_id].cancel()

            # Создаем новый таймер
            timer = threading.Timer(duration, close_relay)
            self._button_timers[button_id] = timer
            timer.start()
            logger.debug(f"Кнопка {button_id}: таймер закрытия {relay_name} на {duration}с запущен")


# Глобальный экземпляр для обратной совместимости
_button_handler = ButtonHandler()


def handle_button_pressed(event: ButtonPressed, turnstile, event_bus, devices: dict) -> None:
    """Обработать событие нажатия кнопки (legacy interface)."""
    _button_handler.handle(event, turnstile, event_bus, devices)
