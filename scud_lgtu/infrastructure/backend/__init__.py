"""Backend infrastructure."""
from scud_lgtu.infrastructure.backend.client import BackendClient
from scud_lgtu.domain.ports import BackendGateway
from scud_lgtu.domain.models import Passage
from typing import List


class BackendGatewayAdapter:
    """Adapter for BackendClient to implement BackendGateway."""
    
    def __init__(self, client: BackendClient):
        """Initialize adapter with client."""
        self._client = client
    
    def is_online(self) -> bool:
        """Check if backend is online."""
        return self._client.is_online()
    
    def get_access_list(self) -> dict:
        """Get access list from backend."""
        return self._client.get_access_list()
    
    def send_events(self, events: List[Passage]) -> bool:
        """Send events to backend."""
        # Convert domain Passage events to backend format
        # This is a placeholder - actual implementation depends on backend API
        return self._client.send_events([])
