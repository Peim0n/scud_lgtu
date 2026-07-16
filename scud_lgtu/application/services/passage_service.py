"""Сервис журналирования проходов."""
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
