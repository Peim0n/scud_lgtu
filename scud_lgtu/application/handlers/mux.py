"""Обработчик событий мультиплексора."""
from scud_lgtu.domain.events import MuxInputChanged, ButtonPressed, AlarmChanged
import logging

logger = logging.getLogger(__name__)

# Храним предыдущие состояния кнопок для детекции фронтов
_button_states = {}


def handle_mux_input_changed(event: MuxInputChanged, event_bus) -> None:
    """Обработать событие изменения входа мультиплексора."""
    logger.info(f"handle_mux_input_changed: {event}")
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
            logger.info(f"Publishing ButtonPressed: {button_event}")
            event_bus.publish(button_event)
        elif prev_state is None:
            logger.info(f"Button {event.input_name} initial state: {event.state}")
    elif event.input_name == "alarm":
        # Событие тревоги
        alarm_event = AlarmChanged(
            active=event.state
        )
        logger.info(f"Publishing AlarmChanged: {alarm_event}")
        event_bus.publish(alarm_event)
    # Другие входы мультиплексора могут обрабатываться аналогично
