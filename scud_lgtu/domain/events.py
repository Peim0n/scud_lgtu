"""События домена."""
from dataclasses import dataclass
from typing import Optional, List
from scud_lgtu.domain.models import Credential, OutputCommand
from scud_lgtu.domain.enums import DirectionEnum


@dataclass
class QrRead:
    """
    Событие считывания QR-кода.

    Attributes
    ----------
    credential : Credential
        Учётные данные из QR-кода
    reader_id : str
        Идентификатор считывателя QR-кодов
    """
    credential: Credential
    reader_id: str


@dataclass
class CardRead:
    """
    Событие считывания карты.

    Attributes
    ----------
    credential : Credential
        Учётные данные с карты
    reader_id : str
        Идентификатор считывателя карт (Wiegand)
    """
    credential: Credential
    reader_id: str


@dataclass
class PassageDetected:
    """
    Событие обнаружения прохода.

    Attributes
    ----------
    direction : str
        Направление прохода: "in" (вход), "out" (выход), "turnback" (разворот), "blockage" (заслон)
    zone : str
        Зона прохода (идентификатор датчика)
    duration : float
        Длительность прохода в секундах
    token : str, optional
        Токен авторизации для связывания с сессией
    """
    direction: str  # "in", "out", "turnback", "blockage"
    zone: str
    duration: float
    token: Optional[str] = None  # Токен авторизации для связывания с сессией


@dataclass
class AlarmChanged:
    """
    Событие изменения состояния тревоги.

    Attributes
    ----------
    active : bool
        True если тревога активирована, False если деактивирована
    """
    active: bool


@dataclass
class ButtonPressed:
    """
    Событие нажатия кнопки.

    Attributes
    ----------
    button_id : str
        Идентификатор кнопки (например, "button_1", "button_2")
    state : bool
        Состояние кнопки (False = нажата, True = отжата)
    """
    button_id: str
    state: bool


@dataclass
class MuxInputChanged:
    """
    Событие изменения входа мультиплексора.

    Attributes
    ----------
    input_name : str
        Имя входа мультиплексора (например, "sensor_1", "button_1")
    state : bool
        Состояние входа (True = активен, False = неактивен)
    """
    input_name: str
    state: bool


@dataclass
class OutputCommandsGenerated:
    """
    Событие генерации команд для выхода.

    Attributes
    ----------
    commands : List[OutputCommand]
        Список команд для управления выходами оборудования
    """
    commands: List[OutputCommand]
