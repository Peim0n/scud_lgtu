"""
Модуль с базовыми методами бизнес-логики для Scud_Lgtu.
"""

import time
import queue
import logging
from typing import Optional, Tuple

from .data_types import ScudEvent, ScudCommand, EventType, EventSource, CommandTarget, CommandAction, PassageEvent
from .qr_handler import QRDecoder

logger = logging.getLogger(__name__)


# === Работа с событиями ===

def get_event(engine, timeout: float = 0.2) -> Optional[ScudEvent]:
    """Получить событие из очереди."""
    events = engine.get_event_queue()
    try:
        return events.get(timeout=timeout)
    except queue.Empty:
        return None

def is_card_read(event: ScudEvent) -> bool:
    """Проверка типа события (карта)."""
    return event.type == EventType.CARD_READ

def is_qr_read(event: ScudEvent) -> bool:
    """Проверка типа события (QR)."""
    return event.type == EventType.QR_READ

def is_passage_event(event: ScudEvent) -> bool:
    """Проверка типа события (проход)."""
    return event.type == EventType.INPUT_SIGNAL

def is_serial_data(event: ScudEvent) -> bool:
    """Проверка типа события (serial)."""
    return event.type == EventType.SERIAL_DATA


# === Проверка доступа ===

def check_card_access(cache, token: str) -> Tuple[bool, Optional[int]]:
    """Проверка доступа по карте."""
    return cache.is_allowed("cardid", token)

def check_qr_access(cache, url: str) -> Tuple[bool, Optional[int]]:
    """Проверка доступа по QR."""
    qr = QRDecoder()
    try:
        qr_fields = qr.decode_url(url)
        max_id = qr_fields.get("max_id")
        if max_id is None:
            return False, None
        return cache.is_allowed("maxid", str(max_id))
    except Exception:
        return False, None

def check_access(cache, token_type: str, token: str) -> Tuple[bool, Optional[int]]:
    """Универсальная проверка доступа."""
    return cache.is_allowed(token_type, token)


# === Управление сдвиговым регистром через set_mask ===

def set_shift_pins(engine, masks: dict[str, bool]) -> None:
    """Установить несколько пинов атомарно по именам."""
    if engine._pct is not None:
        engine._pct.set_mask(masks)


# === Управление турникетом ===

def open_turnstile(engine) -> None:
    """Открыть турникет (REL2)."""
    set_shift_pins(engine, {"rel2": True})

def close_turnstile(engine) -> None:
    """Закрыть турникет (REL2)."""
    set_shift_pins(engine, {"rel2": False})


# === Управление индикаторами ===

def set_green_indicator(engine, reader: str = "w1") -> None:
    """Включить зеленый индикатор."""
    set_shift_pins(engine, {f"{reader}_green": True})

def set_red_indicator(engine, reader: str = "w1") -> None:
    """Включить красный индикатор."""
    set_shift_pins(engine, {f"{reader}_red": True})

def turn_off_indicator(engine, reader: str = "w1", color: str = "green") -> None:
    """Выключить индикатор."""
    set_shift_pins(engine, {f"{reader}_{color}": False})

def flash_indicator(engine, reader: str = "w1", color: str = "green", count: int = 3, on_time: float = 0.2, off_time: float = 0.2) -> None:
    """Мигание индикатора."""
    for _ in range(count):
        set_shift_pins(engine, {f"{reader}_{color}": True})
        time.sleep(on_time)
        set_shift_pins(engine, {f"{reader}_{color}": False})
        time.sleep(off_time)

def set_indicator_with_timeout(engine, reader: str = "w1", color: str = "green", duration: float = 2.0) -> None:
    """Включить индикатор на время и выключить."""
    set_shift_pins(engine, {f"{reader}_{color}": True})
    time.sleep(duration)
    set_shift_pins(engine, {f"{reader}_{color}": False})


# === Управление пищалкой ===

def beep(engine) -> None:
    """Короткий сигнал пищалки (BUZ)."""
    set_shift_pins(engine, {"buz": True})
    time.sleep(0.05)
    set_shift_pins(engine, {"buz": False})

def w1_beep(engine) -> None:
    """Короткий сигнал пищалки Wiegand 1."""
    set_shift_pins(engine, {"w1_beep": True})
    time.sleep(0.05)
    set_shift_pins(engine, {"w1_beep": False})

def w2_beep(engine) -> None:
    """Короткий сигнал пищалки Wiegand 2."""
    set_shift_pins(engine, {"w2_beep": True})
    time.sleep(0.05)
    set_shift_pins(engine, {"w2_beep": False})

def pult_beep(engine) -> None:
    """Короткий сигнал пищалки на пульте."""
    set_shift_pins(engine, {"pult_buzz": True})
    time.sleep(0.05)
    set_shift_pins(engine, {"pult_buzz": False})

def beep_sequence(engine, count: int = 3) -> None:
    """Последовательность сигналов пищалки (BUZ)."""
    for _ in range(count):
        beep(engine)
        time.sleep(0.1)

def beep_custom(engine, buzzer: str = "buz", on_time: float = 0.05, off_time: float = 0.05) -> None:
    """Кастомный бип с настраиваемой длительностью."""
    set_shift_pins(engine, {buzzer: True})
    time.sleep(on_time)
    set_shift_pins(engine, {buzzer: False})
    time.sleep(off_time)

def beep_repeat(engine, buzzer: str = "buz", count: int = 3, on_time: float = 0.05, off_time: float = 0.1) -> None:
    """Повторяющийся бип с настройкой количества и задержек."""
    for _ in range(count):
        set_shift_pins(engine, {buzzer: True})
        time.sleep(on_time)
        set_shift_pins(engine, {buzzer: False})
        time.sleep(off_time)


# === Управление пультом ===

def set_pult_indicator(engine, l1: bool = False, l2: bool = False, l3: bool = False) -> None:
    """Установить индикаторы на пульте."""
    set_shift_pins(engine, {
        "pult_l1": l1,
        "pult_l2": l2,
        "pult_l3": l3,
    })


# === Управление выходами OD ===

def set_od1(engine, state: bool) -> None:
    """Установить выход OD1."""
    set_shift_pins(engine, {"od1": state})

def set_od2(engine, state: bool) -> None:
    """Установить выход OD2."""
    set_shift_pins(engine, {"od2": state})


# === Обработка проходов ===

def get_passage_direction(event: ScudEvent) -> Optional[str]:
    """Получить направление прохода."""
    return event.payload.get("direction")

def get_passage_zone(event: ScudEvent) -> Optional[str]:
    """Получить зону прохода."""
    return event.payload.get("zone")

def is_passage_in(event: ScudEvent) -> bool:
    """Проверка входа."""
    return event.payload.get("direction") == "in"

def is_passage_out(event: ScudEvent) -> bool:
    """Проверка выхода."""
    return event.payload.get("direction") == "out"

def is_blockage(event: ScudEvent) -> bool:
    """Проверка заслона."""
    return event.payload.get("direction") == "blockage"


# === Работа с событиями кнопок ===

def is_button_event(event: ScudEvent, button_name: str) -> bool:
    """Проверить событие нажатия кнопки."""
    return (event.type == EventType.INPUT_SIGNAL and 
            event.payload.get("input_name") == button_name and
            event.payload.get("state") == True)

def is_button_1_pressed(event: ScudEvent) -> bool:
    """Проверить нажатие кнопки 1."""
    return is_button_event(event, "button_1")

def is_button_2_pressed(event: ScudEvent) -> bool:
    """Проверить нажатие кнопки 2."""
    return is_button_event(event, "button_2")

def is_button_3_pressed(event: ScudEvent) -> bool:
    """Проверить нажатие кнопки 3."""
    return is_button_event(event, "button_3")


# === Работа с алармом ===

def is_alarm_event(event: ScudEvent) -> bool:
    """Проверить событие аларма."""
    return (event.type == EventType.INPUT_SIGNAL and 
            event.payload.get("input_name") == "alarm")

def is_alarm_active(event: ScudEvent) -> bool:
    """Проверить активность аларма (False = активный аларм)."""
    return is_alarm_event(event) and event.payload.get("state") == False


# === Типовые сценарии доступа ===

def grant_access(engine, reader: str = "w1", duration: float = 2.0) -> None:
    """Разрешить доступ: зеленый индикатор + открытие турникета."""
    set_shift_pins(engine, {f"{reader}_green": True, "rel2": True})
    time.sleep(0.5)  # Зеленый индикатор горит 0.5 секунды
    set_shift_pins(engine, {f"{reader}_green": False})  # Выключаем индикатор, реле остается
    time.sleep(duration - 0.5)  # Реле остается открытым оставшееся время
    set_shift_pins(engine, {"rel2": False})  # Выключаем реле

def deny_access(engine, reader: str = "w1", beep_count: int = 3) -> None:
    """Отказать в доступе: красный индикатор + 3 быстрых пика."""
    set_shift_pins(engine, {f"{reader}_red": True})
    # 3 быстрых пика
    for _ in range(3):
        set_shift_pins(engine, {"buz": True})
        time.sleep(0.05)
        set_shift_pins(engine, {"buz": False})
        time.sleep(0.05)
    time.sleep(1.0)
    set_shift_pins(engine, {f"{reader}_red": False})


# === Авторизация ===

def authorize_passage(direction: str, token_type: str, token: str, user_id: Optional[int] = None) -> dict:
    """Запомнить успешную авторизацию. Возвращает словарь авторизации."""
    return {
        "time": time.time(),
        "direction": direction,
        "used": False,
        "token_type": token_type,
        "token": token,
        "user_id": user_id,
    }

def check_authorization(auth: dict, direction: str, auth_timeout: float) -> bool:
    """Проверить авторизацию для направления."""
    if auth is None:
        return False
    if time.time() - auth["time"] > auth_timeout:
        return False
    if auth["direction"] != direction:
        return False
    if auth["used"]:
        return False
    return True

def mark_auth_used(auth: dict) -> None:
    """Пометить авторизацию как использованную."""
    if auth:
        auth["used"] = True


# === Журналирование ===

def log_passage(store, event_counter: int, result: str, token: str, user_id: Optional[int], description: str) -> int:
    """Записать проход. Возвращает новый счетчик событий."""
    new_counter = event_counter + 1
    event = PassageEvent(
        event_id=new_counter,
        stime=time.time(),
        token_type="cardid",
        token=token,
        user_id=user_id,
        result=result,
        severity="info",
        description=description,
    )
    store.append(event)
    return new_counter

def log_error(message: str) -> None:
    """Записать ошибку."""
    logger.error(message)

def log_info(message: str) -> None:
    """Записать информацию."""
    logger.info(message)


# === Таймауты ===

def check_relay_timeout(relay_open_time: float, relay_duration: float) -> bool:
    """Проверить таймаут реле. Возвращает True если нужно закрыть."""
    if relay_open_time == 0.0:
        return False
    return time.time() - relay_open_time > relay_duration

def check_indicator_timeout(indicator_time: float, indicator_duration: float) -> bool:
    """Проверить таймаут индикатора. Возвращает True если нужно выключить."""
    if indicator_time == 0.0:
        return False
    return time.time() - indicator_time > indicator_duration

def check_auth_timeout(auth: dict, auth_timeout: float) -> bool:
    """Проверить таймаут авторизации."""
    if auth is None:
        return False
    return time.time() - auth["time"] > auth_timeout


# === Синхронизация ===

def sync_with_backend(backend, cache, store) -> None:
    """Синхронизация с бэкендом."""
    if backend.is_online():
        cache.update(backend.get_access_list())
        backend.send_events(store.flush())

def update_cache(cache, access_list: dict) -> None:
    """Обновить кэш."""
    cache.update(access_list)

def send_events(backend, store) -> None:
    """Отправить события."""
    backend.send_events(store.flush())
