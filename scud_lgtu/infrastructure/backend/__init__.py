"""Пакет scud_lgtu.infrastructure.backend."""
import time
from typing import List

from scud_lgtu.infrastructure.backend.client import BackendClient
from scud_lgtu.infrastructure.persistence.event_store import PassageEvent
from scud_lgtu.domain.access.ports.ports import BackendGateway
from scud_lgtu.domain.common.models.models import Passage


class BackendGatewayAdapter:
    """Адаптер BackendClient для реализации BackendGateway."""

    def __init__(self, client: BackendClient):
        """Инициализировать адаптер с клиентом."""
        self._client = client

    def is_online(self) -> bool:
        """Проверить, что бэкенд онлайн."""
        return self._client.is_online()

    def get_access_list(self) -> dict:
        """Получить список доступа из бэкенда."""
        return self._client.get_access_list()

    def send_events(self, events: List[Passage]) -> bool:
        """Отправить события в бэкенд."""
        passage_events = [
            PassageEvent(
                event_id=idx,
                stime=time.time(),
                direction=event.direction.value,
                result=event.result.value,
                description=f"zone={event.zone}, duration={event.duration}",
            )
            for idx, event in enumerate(events)
        ]
        return self._client.send_events(passage_events)
