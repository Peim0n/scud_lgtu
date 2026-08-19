"""Перечисления пакета app.domain.common.enums."""
from enum import Enum


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
    CARDID_PARTIAL_H = "cardid_partial_h"
    # Внутренний тип (не из ТЗ): значение уже прошло SHA256+HMAC(STATIC_KEY)
    # на считывателе (режим "HMAC-SHA256(SHA256(PAN), KEY)" у ЭРА/аналогов) и
    # обрезано до 8 байт Wiegand-кадром. Требует только финального
    # HMAC(..., DYNAMIC_KEY) перед сравнением со списком cardid_h.


class ResultEnum(str, Enum):
    """Результат прохода (п. 5.5 ТЗ)."""
    PASS = "pass"
    TIMEOUT = "timeout"
    DENIED = "denied"
    ONCOMING = "oncoming"
    DOUBLE = "double"
    FORCED = "forced"
    BLOCKAGE = "blockage"
    TURNBACK = "turnback"


class SeverityEnum(str, Enum):
    """Важность события (п. 5.5 ТЗ)."""
    FATAL = "fatal"
    CRITICAL = "critical"
    ERROR = "error"
    WARNING = "warning"
    NOTICE = "notice"
    INFO = "info"
    DEBUG = "debug"


class EventTypeEnum(str, Enum):
    """Типы событий в таблице log (п. 5.5 ТЗ)."""
    ACCESS = "access"
    SYSTEM = "system"
    FIRMWARE = "firmware"
    SECURITY = "security"
    CONNECTION = "connection"
