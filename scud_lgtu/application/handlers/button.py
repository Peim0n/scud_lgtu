"""Обработчик событий кнопок."""
from scud_lgtu.domain.events import ButtonPressed
from scud_lgtu.domain.enums import DirectionEnum


def handle_button_pressed(event: ButtonPressed, turnstile) -> None:
    """Обработать событие нажатия кнопки."""
    if event.button_id == "button_1":
        # Открыть для входа
        commands = turnstile.open_entry()
    elif event.button_id == "button_2":
        # Открыть для выхода
        commands = turnstile.open_exit()
    elif event.button_id == "button_3":
        # Обработка кнопки 3 (может быть что-то другое)
        commands = turnstile.close()
    else:
        # Неизвестная кнопка - закрыть турникет
        commands = turnstile.close()
    
    # Применение команд через исполнительный механизм (для реализации)
