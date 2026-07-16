"""Порты домена (интерфейсы)."""
from typing import Protocol, Optional, List
from scud_lgtu.domain.models import Credential, AccessDecision, Passage, OutputCommand


class AccessRepository(Protocol):
    """Репозиторий для проверок доступа."""
    
    def is_allowed(self, credential: Credential) -> AccessDecision:
        """Проверить, разрешены ли учётные данные."""
        ...


class EventLog(Protocol):
    """Журнал событий проходов."""
    
    def append(self, passage: Passage) -> None:
        """Добавить событие прохода в журнал."""
        ...
    
    def flush(self) -> List[Passage]:
        """Выгрузить все события и вернуть их."""
        ...


class Actuator(Protocol):
    """Исполнительный механизм для управления выходами оборудования."""
    
    def apply(self, command: OutputCommand) -> None:
        """Применить команду вывода."""
        ...


class SoundOutput(Protocol):
    """Вывод звука для воспроизведения эффектов."""
    
    def play(self, effect: str) -> None:
        """Воспроизвести звуковой эффект."""
        ...


class BackendGateway(Protocol):
    """Шлюз для связи с бэкендом."""
    
    def is_online(self) -> bool:
        """Проверить, доступен ли бэкенд."""
        ...
    
    def get_access_list(self) -> dict:
        """Получить список доступа с бэкенда."""
        ...
    
    def send_events(self, events: List[Passage]) -> bool:
        """Отправить события на бэкенд."""
        ...
