"""
Обработчик событий мультиплексора системы СКУД.

Этот модуль реализует обработчик событий изменения входа мультиплексора. Обработчик
преобразует входы мультиплексора в события домена: кнопки (ButtonPressed).
Для кнопок выполняется детекция фронтов нажатия (1 -> 0) и отжатия (0 -> 1)
для корректной обработки нажатий.

Функции
-------
- handle_mux_input_changed: обработать событие изменения входа мультиплексора
"""
from scud_lgtu.domain.common.events.events import MuxInputChanged, ButtonPressed
import logging

logger = logging.getLogger(__name__)

# Храним предыдущие состояния кнопок для детекции фронтов
_button_states = {}


def handle_mux_input_changed(event: MuxInputChanged, event_bus) -> None:
    """Обработать событие изменения входа мультиплексора."""
    logger.debug(f"handle_mux_input_changed: {event}")
    
    # Обрабатываем только кнопки
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
