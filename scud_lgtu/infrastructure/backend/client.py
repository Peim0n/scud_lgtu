"""
Клиент для взаимодействия с бэкендом системы СКУД.

Этот модуль реализует REST API клиент для бэкенда СКУД. В production должен быть заменён
на реальные HTTPS-запросы с mTLS. Текущая реализация является заглушкой для тестирования.

Классы
-------
- BackendClient: REST API клиент для бэкенда СКУД

Методы BackendClient
---------------------
- __init__: инициализировать базовый URL бэкенда
- is_online: проверить доступность бэкенда
- get_access_list: получить список разрешённых идентификаторов
- send_events: отправить накопленные события проходов
"""

import logging
from typing import Any

from scud_lgtu.infrastructure.persistence.event_store import PassageEvent

logger = logging.getLogger(__name__)


class BackendClient:
    def __init__(self, base_url: str = "https://api.pass.lipetsk.ru") -> None:
        self._base_url = base_url

    def is_online(self) -> bool:
        return False

    def get_access_list(self) -> dict[str, Any]:
        logger.warning("BackendClient.get_access_list: заглушка")
        return {}

    def send_events(self, events: list[PassageEvent]) -> None:
        if not events:
            return
        logger.warning("BackendClient.send_events: заглушка, %d событий", len(events))
