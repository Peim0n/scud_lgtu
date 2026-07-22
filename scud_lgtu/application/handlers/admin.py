"""
Обработчик локальных админ-команд.

Команды: lock, unlock, unlock_entry, unlock_exit, cancel_unlock.
Внешний триггер пока не реализован — обработчик готов для подключения к бэкенду.
"""
from scud_lgtu.domain.common.events.events import AdminCommand, OutputCommandsGenerated
import logging

logger = logging.getLogger(__name__)


def handle_admin_command(event: AdminCommand, turnstile, event_bus) -> None:
    """Обработать админ-команду."""
    cmd = event.command
    logger.info(f"Admin command: {cmd}")

    commands = []
    if cmd == "lock":
        commands = turnstile.lock()
    elif cmd == "unlock":
        commands = turnstile.unlock()
    elif cmd == "unlock_entry":
        commands = turnstile.unlock_entry()
    elif cmd == "unlock_exit":
        commands = turnstile.unlock_exit()
    elif cmd == "cancel_unlock":
        commands = turnstile.close()
    else:
        logger.warning(f"Unknown admin command: {cmd}")
        return

    if commands:
        event_bus.publish(OutputCommandsGenerated(commands=commands))
