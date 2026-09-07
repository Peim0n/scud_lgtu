"""
Модели данных, события и хранилище событий (DataTypes) системы СКУД.

Содержит перечисления для событий и команд, классы событий и команд,
перечисления бизнес-логики, модель события прохода и хранилище событий.

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
from enum import Enum
from typing import Any

# ============================================================================
# Событийная модель ScudEngine
# ============================================================================

class EventType(str, Enum):
    """Типы событий от hardware-модулей."""
    BUTTON_PRESSED = "button_pressed"
    ALARM_CHANGED = "alarm_changed"
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
    WATCHDOG = "watchdog"
    ENGINE = "engine"


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
    id: int | None = None                 # bigint, ID записи в БД
    accesspoint_id: int | None = None     # bigint
    event_id: int = 0                        # uint64, порядковый номер на контроллере
    event_type: str = EventTypeEnum.ACCESS.value  # access | system | firmware | security | connection
    direction: str = DirectionEnum.IN.value  # in | out
    stime: float = 0.0                       # timestamptz
    ftime: float | None = None            # timestamptz
    token_type: str = TokenTypeEnum.MAXID.value  # phone | phone_h | maxid | maxid_h | cardid | cardid_h
    token: str = ""
    result: str = ResultEnum.DENIED.value    # pass | timeout | denied | oncoming | double | forced
    severity: str = SeverityEnum.INFO.value  # fatal | critical | error | warning | notice | info | debug
    description: str = ""
    zone: str | None = None               # зона прохода
    duration: float | None = None         # длительность прохода


# ============================================================================
# Хранилище событий
# ============================================================================

class EventStore:
    """
    Локальное in-memory хранилище событий.

    Потокобезопасное хранилище с монотонным ``event_id`` (п. 3 ТЗ,
    "Идемпотентность передачи") для дедупликации на бэкенде.  Ничего
    не пишется на SD-карту — все данные хранятся только в оперативной
    памяти (согласно ТЗ).
    """

    def __init__(self) -> None:
        self._events: list[PassageEvent] = []
        self._next_event_id: int = 1
        self._lock = threading.Lock()

    def append(self, event: PassageEvent) -> None:
        """Добавить событие в хранилище, назначив ему event_id, если он не задан."""
        with self._lock:
            if not event.event_id:
                event.event_id = self._next_event_id
                self._next_event_id += 1
            self._events.append(event)

    def requeue(self, events: list[PassageEvent]) -> None:
        """Вернуть события в начало хранилища (например, после неудачной отправки)."""
        if not events:
            return
        with self._lock:
            self._events = list(events) + self._events

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

    def peek_next_event_id(self) -> int:
        """Следующий event_id, который будет назначен новому событию."""
        with self._lock:
            return self._next_event_id

    def oldest_pending_event_id(self) -> int | None:
        """
        event_id самого старого неотправленного события в очереди.

        Если очередь пуста, возвращает None — это означает, что локально
        нет "хвоста" событий старше ``peek_next_event_id()``, ожидающих
        отправки (используется для сверки с бэкендом, см. SyncService).
        """
        with self._lock:
            return self._events[0].event_id if self._events else None


