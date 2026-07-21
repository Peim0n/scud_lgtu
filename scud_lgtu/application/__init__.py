"""Пакет scud_lgtu.application."""

# События
from scud_lgtu.application.events.event_bus import EventBus

# Оркестрация
from scud_lgtu.application.orchestration.lgtu_application import LGTUApplication

__all__ = [
    # События
    'EventBus',
    # Оркестрация
    'LGTUApplication',
]
