"""Доменные события (domain events) системы СКУД LGTU.

Этот модуль содержит неизменяемые dataclass-события, которые генерируются
инфраструктурными слоями и обрабатываются прикладными слоями через EventBus.
"""
from dataclasses import dataclass
from typing import List, Optional

from scud_lgtu.domain.common.models.models import Credential, OutputCommand


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
    user_id: Optional[int] = None


@dataclass
class PassageStarted:
    """Событие начала прохода (первый датчик сработал)."""
    zone: str
    direction: str
    first_sensor: str


@dataclass
class PassageSensorsCleared:
    """Событие освобождения датчиков прохода (после заслона)."""
    zone: str


@dataclass
class OutputCommandsGenerated:
    """Событие генерации команд управления."""
    commands: List[OutputCommand]
