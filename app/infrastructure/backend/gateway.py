"""Пакет app.infrastructure.backend."""
from typing import Any, List

from app.infrastructure.backend.client import BackendClient
from app.infrastructure.persistence.event_store import PassageEvent


class BackendGatewayAdapter:
    """Адаптер BackendClient для реализации BackendGateway."""

    def __init__(self, client: BackendClient):
        """Инициализировать адаптер с клиентом."""
        self._client = client

    def is_online(self) -> bool:
        """Проверить, что бэкенд онлайн."""
        return self._client.is_online()

    def get_access_list(self, update: int = 1) -> dict:
        """Получить список доступа из бэкенда (§5.4.3)."""
        return self._client.get_access_list(update=update)

    def send_events(self, events: List[PassageEvent]) -> bool:
        """
        Отправить события в бэкенд.

        Принимает уже готовые инфраструктурные ``PassageEvent`` (с
        назначенным ``EventStore`` монотонным ``event_id``) — без
        промежуточного пересобирания, чтобы не терять event_id/token_type,
        нужные для идемпотентности и журнала (§5.5, §6.5).
        """
        return self._client.send_events(events)

    def get_last_event(self) -> dict:
        """Получить event_id последнего события, принятого бэкендом."""
        return self._client.get_last_event()

    def get_keys(self) -> list:
        """Получить наборы ключей QR/карт «МИР» (§5.4.2)."""
        return self._client.get_keys()

    def patch_accesspoint(self, mac: str, ip: str, cpuid: str) -> dict:
        """Отправить инвентаризационные данные контроллера."""
        return self._client.patch_accesspoint(mac, ip, cpuid)
