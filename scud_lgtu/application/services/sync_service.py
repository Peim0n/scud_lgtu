"""
Сервис синхронизации с бэкендом системы СКУД.

Этот модуль реализует сервис для периодической синхронизации событий проходов
и обновления списка доступа с бэкендом. Служит прослойкой между доменной логикой
и инфраструктурой шлюза бэкенда.

Классы
-------
- SyncService: сервис синхронизации с бэкендом

Методы SyncService
------------------
- __init__: инициализировать сервис синхронизации с бэкендом, хранилищем событий и интервалом
- tick: периодический тик для синхронизации
- _sync: выполнить синхронизацию (выгрузка событий и обновление списка доступа)
"""
from scud_lgtu.domain.access.ports.ports import BackendGateway, EventLog
from scud_lgtu.domain.common.models.models import Passage
from typing import List
import time


class SyncService:
    def __init__(self, backend: BackendGateway, event_log: EventLog, sync_interval: float = 60.0):
        self._backend = backend
        self._event_log = event_log
        self._sync_interval = sync_interval
        self._last_sync = 0.0

    def tick(self, now: float) -> None:
        if now - self._last_sync >= self._sync_interval:
            self._sync()
            self._last_sync = now

    def _sync(self) -> None:
        # Выгрузка событий
        events = self._event_log.flush()

        if events and self._backend.is_online():
            # Отправка событий на бэкенд
            self._backend.send_events(events)

        # Обновление списка доступа если бэкенд доступен
        if self._backend.is_online():
            access_list = self._backend.get_access_list()
            # Обновление кэша новым списком доступа (для реализации)
