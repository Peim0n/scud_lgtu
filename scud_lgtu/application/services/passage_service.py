"""
Сервис журналирования проходов системы СКУД.

Этот модуль реализует сервис для записи и выгрузки событий проходов через EventLog.
Служит прослойкой между доменной логикой и инфраструктурой хранилища событий.

Классы
-------
- PassageService: сервис отслеживания проходов

Методы PassageService
----------------------
- __init__: инициализировать сервис проходов с хранилищем событий
- log_passage: записать событие прохода
- flush_events: выгрузить все события проходов
"""
from scud_lgtu.domain.models import Passage
from scud_lgtu.domain.ports import EventLog


class PassageService:
    """Сервис отслеживания проходов."""
    
    def __init__(self, event_log: EventLog):
        """Инициализировать сервис проходов."""
        self._event_log = event_log
    
    def log_passage(self, passage: Passage) -> None:
        """Записать событие прохода."""
        self._event_log.append(passage)
    
    def flush_events(self) -> list[Passage]:
        """Выгрузить все события проходов."""
        return self._event_log.flush()
