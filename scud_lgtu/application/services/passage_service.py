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
from typing import Any, Optional
from scud_lgtu.domain.models import Passage
from scud_lgtu.domain.access import AccessPolicy, PassageTracker


class PassageService:
    def __init__(self, event_log: Any, passage_tracker: Optional[PassageTracker] = None):
        self._event_log = event_log
        self._passage_tracker = passage_tracker

    def log_passage(self, passage: Passage) -> None:
        self._event_log.append(passage)
        if self._passage_tracker is not None and passage.token:
            self._passage_tracker.mark_completed(passage.token)

    def flush_events(self) -> list[Passage]:
        return self._event_log.flush()
