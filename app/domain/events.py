"""Доменные события (domain events) системы СКУД LGTU."""
from dataclasses import dataclass

from app.domain.models import Credential


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
    # Все поля из расшифрованного QR (max_id, phone, timestamp, age_category и т.д.)
    qr_fields: dict | None = None
    # Unix timestamp генерации QR (поле типа 0 из payload) — для проверки возраста
    timestamp: int | None = None
    # Исходный QR URL/строка, полученная от считывателя — для журналирования отказов
    raw_data: str | None = None


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
    token: str | None = None


@dataclass
class AccessGranted:
    """Событие разрешённого доступа."""
    direction: str
    token: str | None = None


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
