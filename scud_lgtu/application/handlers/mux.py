"""Обработчик событий мультиплексора."""
from scud_lgtu.domain.events import MuxInputChanged, ButtonPressed, AlarmChanged


def handle_mux_input_changed(event: MuxInputChanged, event_bus) -> None:
    """Обработать событие изменения входа мультиплексора."""
    # Преобразование входа мультиплексора в события домена
    if event.input_name.startswith("button_"):
        # Событие кнопки
        button_event = ButtonPressed(
            button_id=event.input_name,
            state=event.state
        )
        event_bus.publish(button_event)
    elif event.input_name == "alarm":
        # Событие тревоги
        alarm_event = AlarmChanged(
            active=event.state
        )
        event_bus.publish(alarm_event)
    # Другие входы мультиплексора могут обрабатываться аналогично
