"""События домена."""
from dataclasses import dataclass
from typing import Optional, List
from scud_lgtu.domain.models import Credential, OutputCommand
from scud_lgtu.domain.enums import DirectionEnum


@dataclass
class QrRead:
    """Событие считывания QR-кода."""
    credential: Credential
    reader_id: str


@dataclass
class CardRead:
    """Событие считывания карты."""
    credential: Credential
    reader_id: str


@dataclass
class PassageDetected:
    """Событие обнаружения прохода."""
    direction: DirectionEnum
    zone: str


@dataclass
class AlarmChanged:
    """Событие изменения состояния тревоги."""
    active: bool


@dataclass
class ButtonPressed:
    """Событие нажатия кнопки."""
    button_id: str
    state: bool


@dataclass
class MuxInputChanged:
    """Событие изменения входа мультиплексора."""
    input_name: str
    state: bool


@dataclass
class OutputCommandsGenerated:
    """Событие генерации команд для выхода."""
    commands: List[OutputCommand]
