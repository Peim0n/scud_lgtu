"""
Обработчик событий мультиплексора системы СКУД.

Этот модуль реализует обработчик событий изменения входа мультиплексора. Обработчик
преобразует входы мультиплексора в события домена: кнопки (ButtonPressed) и тревога
(AlarmChanged). Для кнопок выполняется детекция фронтов нажатия (1 -> 0) и отжатия
(0 -> 1) для корректной обработки нажатий.

Функции
-------
- handle_mux_input_changed: обработать событие изменения входа мультиплексора
"""
from scud_lgtu.domain.common.events.events import MuxInputChanged, ButtonPressed, AlarmChanged
import logging

logger = logging.getLogger(__name__)

# Храним предыдущие состояния кнопок и аларма для детекции фронтов
_button_states = {}
_alarm_state = None


def handle_mux_input_changed(event: MuxInputChanged, event_bus) -> None:
    """Обработать событие изменения входа мультиплексора."""
    logger.debug(f"handle_mux_input_changed: {event}")
    # Преобразование входа мультиплексора в события домена
    if event.input_name.startswith("button_"):
        # Детектируем фронт нажатия (1 -> 0)
        prev_state = _button_states.get(event.input_name, None)
        _button_states[event.input_name] = event.state
        
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
    elif event.input_name == "alarm":
        # Детектируем фронт изменения состояния аларма
        prev_state = _alarm_state
        _alarm_state = event.state
        
        # Публикуем событие только при изменении состояния, игнорируем инициализацию (None)
        if prev_state is not None and prev_state != event.state:
            alarm_event = AlarmChanged(
                active=event.state
            )
            logger.info(f"Publishing AlarmChanged: {alarm_event}")
            event_bus.publish(alarm_event)
        elif prev_state is None:
            logger.debug(f"Alarm initial state: {event.state}")
    # Другие входы мультиплексора могут обрабатываться аналогично
