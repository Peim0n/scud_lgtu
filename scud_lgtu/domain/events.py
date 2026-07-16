"""
События домена системы СКУД.

Этот модуль определяет события, которые используются для коммуникации между компонентами системы:
- QrRead: событие считывания QR-кода
- CardRead: событие считывания карты
- PassageDetected: событие обнаружения прохода
- AlarmChanged: событие изменения состояния тревоги
- ButtonPressed: событие нажатия кнопки
- MuxInputChanged: событие изменения входа мультиплексора
- OutputCommandsGenerated: событие генерации команд для выхода

Классы
-------
- QrRead: событие считывания QR-кода с учётными данными и идентификатором считывателя
- CardRead: событие считывания карты с учётными данными и идентификатором считывателя
- PassageDetected: событие прохода с направлением, зоной, длительностью и токеном авторизации
- AlarmChanged: событие изменения состояния тревоги с флагом активности
- ButtonPressed: событие нажатия кнопки с идентификатором и состоянием
- MuxInputChanged: событие изменения входа мультиплексора с именем и состоянием
- OutputCommandsGenerated: событие генерации команд со списком команд для управления выходами
"""
from dataclasses import dataclass
from typing import Optional, List
from scud_lgtu.domain.models import Credential, OutputCommand
from scud_lgtu.domain.enums import DirectionEnum


@dataclass
class QrRead:
    credential: Credential
    reader_id: str


@dataclass
class CardRead:
    credential: Credential
    reader_id: str


@dataclass
class PassageDetected:
    direction: str  # "in", "out", "turnback", "blockage"
    zone: str
    duration: float
    token: Optional[str] = None


@dataclass
class AlarmChanged:
    active: bool


@dataclass
class ButtonPressed:
    button_id: str
    state: bool


@dataclass
class MuxInputChanged:
    input_name: str
    state: bool


@dataclass
class OutputCommandsGenerated:
    commands: List[OutputCommand]
