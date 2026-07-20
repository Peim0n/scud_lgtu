"""Domain events - события доменной области."""
from dataclasses import dataclass
from typing import Optional, List
from scud_lgtu.domain.common.models.models import Credential, OutputCommand
from scud_lgtu.domain.common.enums.enums import DirectionEnum


@dataclass
class CardRead:
    """Событие считывания карты."""
    credential: Credential
    reader_id: str


@dataclass
class QrRead:
    """Событие считывания QR-кода."""
    credential: Credential
    reader_id: str


@dataclass
class MuxInputChanged:
    """Событие изменения входа мультиплексора."""
    input_name: str
    state: bool


@dataclass
class ButtonPressed:
    """Событие нажатия кнопки."""
    button_id: str
    state: bool


@dataclass
class AlarmChanged:
    """Событие изменения состояния тревоги."""
    active: bool


@dataclass
class PassageDetected:
    """Событие обнаружения прохода."""
    direction: str
    zone: str
    duration: float
    token: Optional[str] = None


@dataclass
class OutputCommandsGenerated:
    """Событие генерации команд управления."""
    commands: List[OutputCommand]
