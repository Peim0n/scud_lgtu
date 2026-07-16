"""
scud_lgtu — версия СКУД на gpiod (libgpiod) + threading.

Модули
------
config              Загрузка конфигурации из config.yml
pin_controller      GpiodPinController — управление GPIO через gpiod
mux_worker          MuxWorker — поток опроса мультиплексора
shift_reg_worker    ShiftRegWorker — поток сдвигового регистра
pin_controller_thread PinControllerThread — менеджер потоков GPIO
serial_reader       BackgroundSerialReader — поток чтения UART
wiegand_reader      WeigandReader — поток чтения карт Wiegand
signal_reader       InputSignalReader — поток измерения GPIO-импульсов
signal_writer       OutputSignalWriter — поток управления GPIO-выходами
"""

from .pin_controller import GpiodPinController, PIN_MAP
from .pin_controller_thread import PinControllerThread
from .mux_worker import MuxWorker
from .shift_reg_worker import ShiftRegWorker
from .serial_reader import BackgroundSerialReader
from .wiegand_reader import WeigandReader, CardData, WEIGAND_FORMATS
from .signal_reader import InputSignalReader, InputData
from .signal_writer import OutputSignalWriter, OutputCommand
from .passage_detector import PassageDetector
from .engine import ScudEngine
from .events import ScudEvent, ScudCommand, EventType, EventSource, CommandTarget, CommandAction
from .models import (
    PassageEvent,
    EventTypeEnum,
    DirectionEnum,
    TokenTypeEnum,
    ResultEnum,
    SeverityEnum,
)
from .access_controller import AccessController
from .local_access_cache import LocalAccessCache
from .backend_client import BackendClient
from .event_store import EventStore
from .qr_decoder import QRDecoder
from .identifier_hash import hash_identifier, normalize

__all__ = [
    "GpiodPinController",
    "PIN_MAP",
    "PinControllerThread",
    "MuxWorker",
    "ShiftRegWorker",
    "BackgroundSerialReader",
    "WeigandReader",
    "CardData",
    "WEIGAND_FORMATS",
    "InputSignalReader",
    "InputData",
    "OutputSignalWriter",
    "OutputCommand",
    "PassageDetector",
    "ScudEngine",
    "ScudEvent",
    "ScudCommand",
    "EventType",
    "EventSource",
    "CommandTarget",
    "CommandAction",
    "PassageEvent",
    "EventTypeEnum",
    "DirectionEnum",
    "TokenTypeEnum",
    "ResultEnum",
    "SeverityEnum",
    "AccessController",
    "LocalAccessCache",
    "BackendClient",
    "EventStore",
    "QRDecoder",
    "hash_identifier",
    "normalize",
]
