"""Доменный слой — бизнес-логика системы СКУД."""

# Общие модели
from scud_lgtu.domain.common.models.models import Credential, AccessDecision, AuthSession, Passage, OutputCommand

# Общие перечисления
from scud_lgtu.domain.common.enums.enums import DirectionEnum, TokenTypeEnum, ResultEnum, SeverityEnum, EventTypeEnum

# Общие события
from scud_lgtu.domain.common.events.events import CardRead, QrRead, MuxInputChanged, ButtonPressed, AlarmChanged, PassageDetected, OutputCommandsGenerated

# Сервисы доступа
from scud_lgtu.domain.access.services.services import AccessPolicy, PassageTracker, CredentialHasher

# Порты доступа
from scud_lgtu.domain.access.ports.ports import AccessRepository, EventLog, Actuator, SoundOutput, BackendGateway, ConfigResolver

# Сервисы турникета
from scud_lgtu.domain.turnstile.services.turnstile import TurnstileState, TurnstileStateEnum

__all__ = [
    # Общие модели
    'Credential', 'AccessDecision', 'AuthSession', 'Passage', 'OutputCommand',
    # Общие перечисления
    'DirectionEnum', 'TokenTypeEnum', 'ResultEnum', 'SeverityEnum', 'EventTypeEnum',
    # Общие события
    'CardRead', 'QrRead', 'MuxInputChanged', 'ButtonPressed', 'AlarmChanged', 'PassageDetected', 'OutputCommandsGenerated',
    # Сервисы доступа
    'AccessPolicy', 'PassageTracker', 'CredentialHasher',
    # Порты доступа
    'AccessRepository', 'EventLog', 'Actuator', 'SoundOutput', 'BackendGateway', 'ConfigResolver',
    # Сервисы турникета
    'TurnstileState', 'TurnstileStateEnum',
]
