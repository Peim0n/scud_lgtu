"""Domain layer - бизнес-логика системы СКУД."""

# Common models
from scud_lgtu.domain.common.models.models import Credential, AccessDecision, AuthSession, Passage, OutputCommand

# Common enums
from scud_lgtu.domain.common.enums.enums import DirectionEnum, TokenTypeEnum, ResultEnum, SeverityEnum, EventTypeEnum

# Common events
from scud_lgtu.domain.common.events.events import CardRead, QrRead, MuxInputChanged, ButtonPressed, AlarmChanged, PassageDetected, OutputCommandsGenerated

# Access services
from scud_lgtu.domain.access.services.services import AccessPolicy, PassageTracker, CredentialHasher

# Access ports
from scud_lgtu.domain.access.ports.ports import AccessRepository, EventLog, Actuator, SoundOutput, BackendGateway, ConfigResolver

# Turnstile services
from scud_lgtu.domain.turnstile.services.turnstile import TurnstileState, TurnstileStateEnum

__all__ = [
    # Common models
    'Credential', 'AccessDecision', 'AuthSession', 'Passage', 'OutputCommand',
    # Common enums
    'DirectionEnum', 'TokenTypeEnum', 'ResultEnum', 'SeverityEnum', 'EventTypeEnum',
    # Common events
    'CardRead', 'QrRead', 'MuxInputChanged', 'ButtonPressed', 'AlarmChanged', 'PassageDetected', 'OutputCommandsGenerated',
    # Access services
    'AccessPolicy', 'PassageTracker', 'CredentialHasher',
    # Access ports
    'AccessRepository', 'EventLog', 'Actuator', 'SoundOutput', 'BackendGateway', 'ConfigResolver',
    # Turnstile services
    'TurnstileState', 'TurnstileStateEnum',
]
