"""
Обработчик событий мультиплексора системы СКУД.

Этот модуль реализует обработчик событий изменения входа мультиплексора. Обработчик
преобразует входы мультиплексора в события домена: кнопки (ButtonPressed) и тревога
(AlarmChanged). Для кнопок выполняется детекция фронтов нажатия (1 -> 0) и отжатия
(0 -> 1) для корректной обработки нажатий.

Классы
-------
- MuxInputHandler: обработчик событий мультиплексора с хранением состояния
"""
from scud_lgtu.domain.common.events.events import MuxInputChanged, ButtonPressed, AlarmChanged
import logging

logger = logging.getLogger(__name__)


class MuxInputHandler:
    """Обработчик событий мультиплексора с хранением состояния."""
    
    def __init__(self):
        self._button_states = {}
        self._alarm_state = None
    
    def handle(self, event: MuxInputChanged, event_bus) -> None:
        """Обработать событие изменения входа мультиплексора."""
        logger.debug(f"handle_mux_input_changed: {event}")
        
        if event.input_name.startswith("button_"):
            self._handle_button(event, event_bus)
        elif event.input_name == "alarm":
            self._handle_alarm(event, event_bus)
    
    def _handle_button(self, event: MuxInputChanged, event_bus) -> None:
        """Обработать событие кнопки."""
        prev_state = self._button_states.get(event.input_name, None)
        self._button_states[event.input_name] = event.state
        
        # Публикуем событие только при изменении состояния, игнорируем инициализацию (None)
        if prev_state is not None and prev_state != event.state:
            button_event = ButtonPressed(
                button_id=event.input_name,
                state=event.state
            )
            logger.debug(f"Publishing ButtonPressed: {button_event}")
            event_bus.publish(button_event)
        elif prev_state is None:
            logger.debug(f"Button {event.input_name} initial state: {event.state}")
    
    def _handle_alarm(self, event: MuxInputChanged, event_bus) -> None:
        """Обработать событие аларма."""
        prev_state = self._alarm_state
        
        # Публикуем событие только при изменении состояния, игнорируем инициализацию (None)
        if prev_state is not None and prev_state != event.state:
            alarm_event = AlarmChanged(
                active=event.state
            )
            logger.info(f"Publishing AlarmChanged: {alarm_event}")
            event_bus.publish(alarm_event)
        elif prev_state is None:
            logger.debug(f"Alarm initial state: {event.state}")
        
        self._alarm_state = event.state


# Глобальный экземпляр для обратной совместимости
_mux_handler = MuxInputHandler()


def handle_mux_input_changed(event: MuxInputChanged, event_bus) -> None:
    """Обработать событие изменения входа мультиплексора (legacy interface)."""
    _mux_handler.handle(event, event_bus)
