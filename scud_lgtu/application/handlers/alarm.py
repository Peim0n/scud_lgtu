"""Обработчик событий тревоги."""
from scud_lgtu.domain.events import AlarmChanged


def handle_alarm_changed(event: AlarmChanged, turnstile) -> None:
    """Обработать событие изменения тревоги."""
    if event.active:
        commands = turnstile.set_alarm()
    else:
        commands = turnstile.clear_alarm()
    # Применение команд через исполнительный механизм (для реализации)
