"""Обработчик событий прохода."""
from scud_lgtu.domain.events import PassageDetected


def handle_passage_detected(event: PassageDetected, turnstile, passage_tracker) -> None:
    """Обработать событие обнаружения прохода."""
    # Отметить проход как завершённый
    # Это упрощённая версия - реальная реализация должна отслеживать сессию
    # Пока просто закрываем турникет
    commands = turnstile.close()
    # Применение команд через исполнительный механизм (для реализации)
