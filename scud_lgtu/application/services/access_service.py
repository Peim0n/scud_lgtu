"""
Сервис контроля доступа системы СКУД.

Этот модуль реализует сервис для проверки учётных данных через репозиторий доступа.
Служит прослойкой между доменной логикой и инфраструктурой кэша доступа.

Классы
-------
- AccessService: сервис контроля доступа

Методы AccessService
---------------------
- __init__: инициализировать сервис контроля доступа с репозиторием
- check_access: проверить, разрешены ли учётные данные
"""
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
