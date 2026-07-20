"""
Модели данных, события и хранилище событий (DataTypes) системы СКУД.

Этот модуль объединяет events.py, event_store.py и models.py в один модуль для
централизованного управления событийной моделью ScudEngine. Содержит перечисления
для событий и команд, классы событий и команд, перечисления бизнес-логики,
модель события прохода и хранилище событий.

Классы
-------
- EventType: типы событий от hardware-модулей
- EventSource: источники событий
- CommandTarget: цели команд от бизнес-логики
- CommandAction: действия команд
- ScudEvent: событие от hardware-модуля
- ScudCommand: команда от бизнес-логики к hardware-модулю
- EventTypeEnum: перечисление типов событий бизнес-логики
- DirectionEnum: перечисление направлений прохода
- TokenTypeEnum: перечисление типов токенов
- ResultEnum: перечисление результатов прохода
- SeverityEnum: перечисление уровней серьёзности
- PassageEvent: модель события прохода
- EventStore: хранилище событий

Методы EventStore
------------------
- __init__: инициализировать хранилище событий
- append: добавить событие в хранилище
- flush: выгрузить все события из хранилища
- clear: очистить хранилище
"""

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Optional
from enum import Enum


# ============================================================================
# Событийная модель ScudEngine
# ============================================================================

class EventType(str, Enum):
    """Типы событий от hardware-модулей."""
    MUX_CHANGED = "mux_changed"
    SHIFT_DONE = "shift_done"
    CARD_READ = "card_read"
    QR_READ = "qr_read"
    SERIAL_DATA = "serial_data"
    INPUT_SIGNAL = "input_signal"
    OUTPUT_STATE = "output_state"
    ERROR = "error"
    HEALTH = "health"
    STOP = "stop"


class EventSource(str, Enum):
    """Источники событий."""
    MUX = "mux"
    SHIFT = "shift"
    WIEGAND = "wiegand"
    SERIAL = "serial"
    SIGNAL = "signal"
    WATCHDOG = "watchdog"
    ENGINE = "engine"


class CommandTarget(str, Enum):
    """Цели команд от бизнес-логики."""
    SHIFT = "shift"
    GPIO = "gpio"
    OUTPUT = "output"
    ENGINE = "engine"


class CommandAction(str, Enum):
    """Действия команд."""
    WRITE_SHIFT = "write_shift"
    SET_PIN = "set_pin"
    SET_OUTPUTS_BULK = "set_outputs_bulk"
    SET_OUTPUT = "set_output"
    RESET = "reset"
    STOP = "stop"
    GET_STATE = "get_state"


@dataclass(slots=True)
class ScudEvent:
    """Событие от hardware-модуля."""
    type: EventType | str
    source: EventSource | str
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        """Приведение enum-значений к строкам для JSON-сериализации."""
        if isinstance(self.type, Enum):
            self.type = self.type.value
        if isinstance(self.source, Enum):
            self.source = self.source.value


@dataclass(slots=True)
class ScudCommand:
    """Команда от бизнес-логики к hardware-модулю."""
    target: CommandTarget | str
    action: CommandAction | str
    payload: dict[str, Any] = field(default_factory=dict)
    request_id: Optional[str] = None

    def __post_init__(self) -> None:
        """Приведение enum-значений к строкам для JSON-сериализации."""
        if isinstance(self.target, Enum):
            self.target = self.target.value
        if isinstance(self.action, Enum):
            self.action = self.action.value


# ============================================================================
# Модели данных бизнес-логики
# ============================================================================

class EventTypeEnum(str, Enum):
    """Типы событий в таблице log (п. 5.5 ТЗ)."""
    ACCESS = "access"
    SYSTEM = "system"
    FIRMWARE = "firmware"
    SECURITY = "security"
    CONNECTION = "connection"


class DirectionEnum(str, Enum):
    """Направление прохода (п. 5.5 ТЗ)."""
    IN = "in"
    OUT = "out"


class TokenTypeEnum(str, Enum):
    """Тип идентификатора (п. 5.5 ТЗ)."""
    PHONE = "phone"
    PHONE_H = "phone_h"
    MAXID = "maxid"
    MAXID_H = "maxid_h"
    CARDID = "cardid"
    CARDID_H = "cardid_h"


class ResultEnum(str, Enum):
    """Результат прохода (п. 5.5 ТЗ)."""
    PASS = "pass"
    TIMEOUT = "timeout"
    DENIED = "denied"
    ONCOMING = "oncoming"
    DOUBLE = "double"
    FORCED = "forced"


class SeverityEnum(str, Enum):
    """Важность события (п. 5.5 ТЗ)."""
    FATAL = "fatal"
    CRITICAL = "critical"
    ERROR = "error"
    WARNING = "warning"
    NOTICE = "notice"
    INFO = "info"
    DEBUG = "debug"


@dataclass
class PassageEvent:
    """
    Событие прохода, готовое к журналированию и отправке на бэкенд.

    Соответствует таблице log из п. 5.5 ТЗ.
    """
    id: Optional[int] = None                 # bigint, ID записи в БД
    accesspoint_id: Optional[int] = None     # bigint
    event_id: int = 0                        # uint64, порядковый номер на контроллере
    event_type: str = EventTypeEnum.ACCESS.value  # access | system | firmware | security | connection
    direction: str = DirectionEnum.IN.value  # in | out
    stime: float = 0.0                       # timestamptz
    ftime: Optional[float] = None            # timestamptz
    user_id: Optional[int] = None            # bigint
    token_type: str = TokenTypeEnum.MAXID.value  # phone | phone_h | maxid | maxid_h | cardid | cardid_h
    token: str = ""
    result: str = ResultEnum.DENIED.value    # pass | timeout | denied | oncoming | double | forced
    severity: str = SeverityEnum.INFO.value  # fatal | critical | error | warning | notice | info | debug
    description: str = ""


# ============================================================================
# Хранилище событий
# ============================================================================

class EventStore:
    """
    Локальное хранилище событий.

    Потокобезопасное in-memory хранилище. В production — SQLite с ротацией.
    """

    def __init__(self) -> None:
        """Создать потокобезопасное in-memory хранилище событий."""
        self._events: list[PassageEvent] = []
        self._lock = threading.Lock()

    def append(self, event: PassageEvent) -> None:
        """Добавить событие в хранилище."""
        with self._lock:
            self._events.append(event)

    def flush(self) -> list[PassageEvent]:
        """Извлечь все накопленные события и очистить хранилище."""
        with self._lock:
            events = self._events
            self._events = []
        return events

    def count(self) -> int:
        """Текущее количество событий в хранилище."""
        with self._lock:
            return len(self._events)
