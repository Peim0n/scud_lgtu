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
from scud_lgtu.domain.common.models.models import Credential, AccessDecision
from scud_lgtu.domain.access.ports.ports import AccessRepository


class AccessService:
    def __init__(self, repository: AccessRepository):
        self._repository = repository

    def check_access(self, credential: Credential) -> AccessDecision:
        return self._repository.is_allowed(credential)
