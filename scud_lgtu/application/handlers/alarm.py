"""
Обработчик событий тревоги системы СКУД.

Этот модуль реализует обработчик событий изменения состояния тревоги (пожарной сигнализации).
При активации тревоги открывает все реле и включает индикаторы/бипер для обеспечения
безопасной эвакуации. При деактивации возвращает систему в нормальное состояние.

Функции
-------
- handle_alarm_changed: обработать событие изменения тревоги
"""
from scud_lgtu.domain.common.events.events import AlarmChanged, OutputCommandsGenerated
import logging

logger = logging.getLogger(__name__)


def handle_alarm_changed(event: AlarmChanged, turnstile, event_bus) -> None:
    """
    Обработать событие изменения тревоги.

    Parameters
    ----------
    event : AlarmChanged
        Событие изменения состояния тревоги
    turnstile : TurnstileState
        Состояние турникета для управления
    event_bus : EventBus
        Шина событий для публикации команд
    """
    if event.active:
        commands = turnstile.set_alarm()
        logger.debug(f"Alarm activated, commands: {commands}")
    else:
        commands = turnstile.clear_alarm()
        logger.debug(f"Alarm cleared, commands: {commands}")

    # Публикуем команды через event_bus
    if commands:
        commands_event = OutputCommandsGenerated(commands=commands)
        event_bus.publish(commands_event)
