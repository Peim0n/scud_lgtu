"""
Модели данных бизнес-логики.
"""

from dataclasses import dataclass, field
from typing import Optional
from enum import Enum


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
