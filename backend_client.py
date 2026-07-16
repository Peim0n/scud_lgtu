"""
Клиент для взаимодействия с бэкендом.

Заглушка: реальная реализация потребует mTLS + HTTPS + JSON.
"""

import logging
from typing import Any

from .models import PassageEvent

logger = logging.getLogger(__name__)


class BackendClient:
    """
    REST API клиент для бэкенда СКУД.

    В production заменить на реальные HTTPS-запросы с mTLS.
    """

    def __init__(self, base_url: str = "https://api.pass.lipetsk.ru") -> None:
        """Инициализировать базовый URL бэкенда."""
        self._base_url = base_url

    def is_online(self) -> bool:
        """Проверить доступность бэкенда."""
        # TODO: реальная проверка HTTPS ping
        return False

    def get_access_list(self) -> dict[str, Any]:
        """Получить список разрешённых идентификаторов."""
        # TODO: реальный запрос /controller/v1/access/get
        logger.warning("BackendClient.get_access_list: заглушка")
        return {}

    def send_events(self, events: list[PassageEvent]) -> None:
        """Отправить накопленные события проходов."""
        if not events:
            return
        # TODO: реальный запрос /controller/v1/event/put
        logger.warning("BackendClient.send_events: заглушка, %d событий", len(events))
