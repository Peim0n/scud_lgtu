"""Сервис контроля доступа."""
from scud_lgtu.domain.models import Credential, AccessDecision
from scud_lgtu.domain.ports import AccessRepository


class AccessService:
    """Сервис контроля доступа."""
    
    def __init__(self, repository: AccessRepository):
        """Инициализировать сервис контроля доступа."""
        self._repository = repository
    
    def check_access(self, credential: Credential) -> AccessDecision:
        """Проверить, разрешены ли учётные данные."""
        return self._repository.is_allowed(credential)
