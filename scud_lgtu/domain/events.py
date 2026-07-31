"""Доменные события (domain events) системы СКУД LGTU."""
from dataclasses import dataclass
from typing import List, Optional

from scud_lgtu.domain.models import Credential, OutputCommand


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
class AccessGranted:
    """Событие разрешённого доступа."""
    direction: str
    token: Optional[str] = None
    user_id: Optional[int] = None


@dataclass
class AccessDenied:
    """Событие отказа в доступе."""
    direction: str = ""


@dataclass
class DeviceCommand:
    """Абстрактная команда для устройства доступа (турникет, ворота, дверь)."""
    command: str
    state: bool = False


@dataclass
class AdminCommand:
    """Событие админ-команды."""
    command: str
