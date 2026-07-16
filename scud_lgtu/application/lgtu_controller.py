"""
Модуль контроллера турникета ЛГТУ для системы управления доступом.
Реализует логику обработки QR-кодов, карт МИР, проходов и пожарной сигнализации.
"""

import time
import logging
from typing import Optional

from scud_lgtu.infrastructure.persistence.event_store import ScudEvent, EventType, EventSource
from scud_lgtu.application.basic_business_logic import (
    get_event, is_qr_read, is_card_read, is_passage_event, is_alarm_event, is_serial_data,
    is_button_1_pressed, is_button_2_pressed, is_button_3_pressed,
    get_passage_direction, is_passage_in, is_passage_out, is_blockage,
    check_qr_access, check_card_access, grant_access, deny_access,
    authorize_passage, check_authorization, mark_auth_used,
    log_passage, log_error, log_info,
    open_turnstile, close_turnstile, flash_indicator, turn_off_indicator,
    set_green_indicator, set_red_indicator, beep_sequence, beep_repeat,
    set_indicator_with_timeout, set_shift_pins, is_alarm_active
)
from scud_lgtu.infrastructure.serial.qr_codec import QRDecoder

logger = logging.getLogger(__name__)


class LGTUController:
    """Контроллер турникета ЛГТУ для системы управления доступом."""
    
    def __init__(self, engine, cache, store, backend_client, config):
        """Инициализация контроллера."""
        self.engine = engine
        self.cache = cache
        self.store = store
        self.backend = backend_client
        self.config = config
        self.event_counter = 0
        self.auth_state = None
        
        # Тайминги из конфига
        timings = config.get("timings", {})
        self.auth_timeout = timings.get("auth_timeout_s", 30.0)
        
        self.alarm_active = False
        self.last_passages = {}  # {token: {"direction": "in"/"out", "passed": bool}}
        self.qr_decoder = QRDecoder(keys_dir="scud_lgtu/key")
        self.last_mux_state = {}  # Для отслеживания изменений состояния
        self.button_release_timer = None  # Таймер для закрытия после отжатия кнопки
        self.alarm_thread = None  # Поток индикации аларма
    
    def process_qr_event(self, event: ScudEvent) -> None:
        """Обработка QR-кода (валидация уже реализована в декодере)."""
        log_info(f"QR event received: {event.payload}")
        qr_data = event.payload.get("qr_data")
        if not qr_data:
            deny_access(self.engine)
            log_error("QR event: no data")
            return
        
        max_id = event.payload.get("max_id")
        if not max_id:
            deny_access(self.engine)
            log_error("QR event: no max_id in payload")
            return
        
        allowed, user_id = check_qr_access(self.cache, str(max_id))
        log_info(f"QR access check: max_id={max_id}, allowed={allowed}, user_id={user_id}")
        if allowed:
            self.auth_state = authorize_passage("in", "maxid", str(max_id), user_id)
            log_info(f"QR authorized for {max_id}, calling grant_access")
            grant_access(self.engine)
            log_info(f"grant_access called successfully")
        else:
            log_info(f"QR access denied for {max_id}, calling deny_access")
            deny_access(self.engine)
            self.event_counter = log_passage(self.store, self.event_counter, "denied", str(max_id), None, "QR access denied")
    
    def process_card_event(self, event: ScudEvent) -> None:
        """Обработка карты МИР с учетом шифрования считывателем."""
        log_info(f"Card event received: {event.payload}")
        card_data = event.payload.get("card_data")
        if not card_data:
            deny_access(self.engine)
            log_error("Card event: no card_data")
            return
        
        is_valid = event.payload.get("is_valid", True)
        if not is_valid:
            deny_access(self.engine)
            error_msg = event.payload.get("error_message", "Invalid card")
            log_error(f"Card event: invalid card - {error_msg}")
            return
        
        card_uid = str(card_data)
        log_info(f"Processing card UID: {card_uid}")
        
        is_encrypted = event.payload.get("encrypted", False)
        
        if is_encrypted:
            card_id = card_uid
        else:
            card_id = self.encrypt_card_pan(card_uid)
        
        log_info(f"Checking access for card_id: {card_id}")
        allowed, user_id = check_card_access(self.cache, card_id)
        log_info(f"Access check result: allowed={allowed}, user_id={user_id}")
        
        if allowed:
            self.auth_state = authorize_passage("in", "cardid", card_id, user_id)
            set_green_indicator(self.engine, "w1")
            beep_sequence(self.engine, count=1)
            log_info(f"Card authorized for {card_id}, calling grant_access")
            grant_access(self.engine)
            log_info(f"grant_access called successfully")
        else:
            log_info(f"Card access denied for {card_id}, calling deny_access")
            deny_access(self.engine)
            self.event_counter = log_passage(self.store, self.event_counter, "denied", card_id, None, "Card access denied")
    
    def process_serial_event(self, event: ScudEvent) -> None:
        """Обработка данных из Serial-порта (QR-коды)."""
        reader = event.payload.get("reader", "unknown")
        data = str(event.payload.get("data", "")).strip()
        log_info(f"Serial data from {reader}: {data}")
        
        if data.startswith("https://pass.lipetsk.ru/"):
            log_info(f"QR URL detected from {reader}: {data}")
            try:
                qr_fields = self.qr_decoder.decode_url(data)
                max_id = qr_fields.get("max_id")
                if max_id:
                    qr_event = ScudEvent(
                        type=EventType.QR_READ,
                        source=EventSource.SERIAL,
                        payload={
                            "qr_data": data,
                            "max_id": max_id,
                            "reader": reader
                        }
                    )
                    self.process_qr_event(qr_event)
                else:
                    log_error("QR decode failed: no max_id in result")
                    deny_access(self.engine)
            except Exception as e:
                log_error(f"QR decode failed: {e}")
                deny_access(self.engine)
        else:
            log_info(f"Invalid QR format (not pass.lipetsk.ru): {data}")
            deny_access(self.engine)
    
    def encrypt_card_pan(self, pan: str) -> str:
        """Шифрование PAN карты для сравнения с таблицей разрешенных."""
        # TODO: Реализовать HMAC_SHA256(HMAC_SHA256(SHA256(PAN), STATIC_KEY), DYNAMIC_KEY)
        return pan
    
    def process_passage_event(self, event: ScudEvent) -> None:
        """Обработка события прохода через турникет от датчиков."""
        log_info(f"Passage event received: {event.payload}")
        
        if is_passage_in(event):
            log_info("Passage IN detected")
            self.handle_passage_in(event)
            self.mark_passage_completed("in")
        elif is_passage_out(event):
            log_info("Passage OUT detected")
            self.handle_passage_out(event)
            self.mark_passage_completed("out")
        elif is_blockage(event):
            log_info("Blockage detected")
            self.handle_blockage(event)
    
    def mark_passage_completed(self, direction: str) -> None:
        """Пометить последний проход как завершенный (датчики зафиксировали проход)."""
        for token, passage_info in self.last_passages.items():
            if passage_info["direction"] == direction and not passage_info["passed"]:
                self.last_passages[token]["passed"] = True
                log_info(f"Passage {direction} completed for token {token}")
                break
    
    def handle_passage_in(self, event: ScudEvent) -> None:
        """Обработка входа с проверкой двойного прохода."""
        if not self.auth_state or not check_authorization(self.auth_state, "in", self.auth_timeout):
            deny_access(self.engine)
            self.event_counter = log_passage(self.store, self.event_counter, "denied", "", None, "No authorization for passage in")
            return
        
        token = self.auth_state["token"]
        user_id = self.auth_state["user_id"]
        
        if self.is_double_pass(token, "in"):
            deny_access(self.engine)
            beep_repeat(self.engine, "buz", count=3, on_time=0.05, off_time=0.1)
            set_indicator_with_timeout(self.engine, "w1", "red", duration=1.0)
            self.event_counter = log_passage(self.store, self.event_counter, "denied", token, user_id, "Double passage in detected")
            mark_auth_used(self.auth_state)
            self.auth_state = None
            return
        
        mark_auth_used(self.auth_state)
        grant_access(self.engine)
        self.event_counter = log_passage(self.store, self.event_counter, "pass", token, user_id, "Passage in")
        self.last_passages[token] = {"direction": "in", "passed": False}
        self.auth_state = None
    
    def handle_passage_out(self, event: ScudEvent) -> None:
        """Обработка выхода с проверкой двойного прохода."""
        if not self.auth_state or not check_authorization(self.auth_state, "out", self.auth_timeout):
            deny_access(self.engine)
            self.event_counter = log_passage(self.store, self.event_counter, "denied", "", None, "No authorization for passage out")
            return
        
        token = self.auth_state["token"]
        user_id = self.auth_state["user_id"]
        
        if self.is_double_pass(token, "out"):
            deny_access(self.engine)
            beep_repeat(self.engine, "buz", count=3, on_time=0.05, off_time=0.1)
            set_indicator_with_timeout(self.engine, "w1", "red", duration=1.0)
            self.event_counter = log_passage(self.store, self.event_counter, "denied", token, user_id, "Double passage out detected")
            mark_auth_used(self.auth_state)
            self.auth_state = None
            return
        
        mark_auth_used(self.auth_state)
        grant_access(self.engine)
        self.event_counter = log_passage(self.store, self.event_counter, "pass", token, user_id, "Passage out")
        self.last_passages[token] = {"direction": "out", "passed": False}
        self.auth_state = None
    
    def is_double_pass(self, token: str, direction: str) -> bool:
        """Проверка на двойной проход (если человек уже прошел)."""
        if token not in self.last_passages:
            return False
        
        last_passage = self.last_passages[token]
        
        if last_passage["direction"] == direction and last_passage["passed"]:
            return True
        
        return False
    
    def handle_blockage(self, event: ScudEvent) -> None:
        """Обработка заслона."""
        deny_access(self.engine)
        beep_sequence(self.engine, count=3)
        self.event_counter = log_passage(self.store, self.event_counter, "denied", "", None, "Blockage detected")
    
    def process_alarm_event(self, event: ScudEvent) -> None:
        """Обработка события пожарной сигнализации."""
        log_info(f"Alarm event received: {event.payload}")
        alarm_state = event.payload.get("state")
        log_info(f"Alarm state: {alarm_state}")
        
        fire_alarm_active = bool(alarm_state)
        log_info(f"Fire alarm active: {fire_alarm_active}")
        
        if fire_alarm_active:
            if not self.alarm_active:
                self.alarm_active = True
                log_info("Activating fire alarm mode - opening turnstile and starting indication")
                open_turnstile(self.engine)
                log_info("Turnstile opened via open_turnstile")
                self.start_alarm_indication()
                log_error("Fire alarm active - turnstile unlocked")
        else:
            if self.alarm_active:
                self.alarm_active = False
                log_info("Deactivating fire alarm mode - closing turnstile and stopping indication")
                set_shift_pins(self.engine, {"rel2": False, "w1_red": False, "buz": False, "w1_beep": False, "w2_beep": False})
                log_info("Turnstile closed and indication stopped")
                log_info("Fire alarm cleared - turnstile locked")
    
    def start_alarm_indication(self) -> None:
        """Запустить индикацию пожарной тревоги (мигающий красный + пищание)."""
        import threading
        self.alarm_thread = threading.Thread(target=self._alarm_indication_loop, daemon=True)
        self.alarm_thread.start()
    
    def _alarm_indication_loop(self) -> None:
        """
        Цикл индикации пожарной тревоги.
        
        Мигает реле, индикаторами и бипером с периодом 1 секунда (0.5 сек ON, 0.5 сек OFF).
        """
        alarm_on_duration = 0.5  # Длительность включения (секунды)
        alarm_off_duration = 0.5  # Длительность выключения (секунды)
        
        while self.alarm_active:
            set_shift_pins(self.engine, {"rel2": True, "w1_red": True, "buz": True, "w1_beep": True, "w2_beep": True})
            time.sleep(alarm_on_duration)
            
            if not self.alarm_active:
                break
                
            set_shift_pins(self.engine, {"rel2": True, "w1_red": False, "buz": False, "w1_beep": False, "w2_beep": False})
            time.sleep(alarm_off_duration)
    
    def handle_button_1(self) -> None:
        """Обработка кнопки 1 - открыть на вход (rel1)."""
        log_info("Button 1: opening turnstile for entry (rel1)")
        if self.button_release_timer:
            self.button_release_timer.cancel()
            self.button_release_timer = None
            log_info("Button 1: timer cancelled")
        set_shift_pins(self.engine, {"rel1": True, "w1_green": True})
        self._active_relay = "rel1"
        self._active_indicator = "w1_green"
        log_info("Button 1: turnstile opened (rel1)")
    
    def handle_button_2(self) -> None:
        """Обработка кнопки 2 - открыть на выход (rel2)."""
        log_info("Button 2: opening turnstile for exit (rel2)")
        if self.button_release_timer:
            self.button_release_timer.cancel()
            self.button_release_timer = None
            log_info("Button 2: timer cancelled")
        set_shift_pins(self.engine, {"rel2": True, "w2_green": True})
        self._active_relay = "rel2"
        self._active_indicator = "w2_green"
        log_info("Button 2: turnstile opened (rel2)")
    
    def handle_button_3(self) -> None:
        """Обработка кнопки 3 - не используется."""
        pass
    
    def handle_button_release(self) -> None:
        """Обработка отжатия кнопки - запустить таймер закрытия."""
        log_info("Button released: starting 2s timer to close turnstile")
        if self.button_release_timer:
            self.button_release_timer.cancel()
            log_info("Previous timer cancelled")
        
        import threading
        relay = getattr(self, "_active_relay", "rel2")
        indicator = getattr(self, "_active_indicator", "w1_green")
        self.button_release_timer = threading.Timer(2.0, self._close_turnstile_after_timer)
        self.button_release_timer.start()
        log_info("Timer started: will close turnstile in 2 seconds")
    
    def _close_turnstile_after_timer(self) -> None:
        """Закрыть турникет после таймера."""
        log_info("Timer expired: closing turnstile")
        relay = getattr(self, "_active_relay", "rel2")
        indicator = getattr(self, "_active_indicator", "w1_green")
        set_shift_pins(self.engine, {relay: False, indicator: False})
        self.button_release_timer = None
        log_info(f"Turnstile closed after timer ({relay}, {indicator})")
    
    def process_mux_event(self, event: ScudEvent) -> None:
        """Обработка событий от мультиплексора (кнопки, аларм, датчики)."""
        states = event.payload.get("states", {})
        log_info(f"MUX event received: {states}")
        
        for key, value in states.items():
            if key not in self.last_mux_state:
                self.last_mux_state[key] = value
                continue
            
            old_value = self.last_mux_state[key]
            if old_value != value:
                log_info(f"State change detected: {key}: {old_value} -> {value}")
                self.last_mux_state[key] = value
                
                if key == "button_1":
                    if value == 0:
                        log_info("Button 1 pressed (state=0)")
                        self.handle_button_1()
                    else:
                        log_info("Button 1 released (state=1)")
                        self.handle_button_release()
                elif key == "button_2":
                    if value == 0:
                        log_info("Button 2 pressed (state=0)")
                        self.handle_button_2()
                    else:
                        log_info("Button 2 released (state=1)")
                        self.handle_button_release()
                elif key == "alarm":
                    log_info(f"Alarm state changed: {value}")
                    alarm_event = ScudEvent(
                        type=EventType.INPUT_SIGNAL,
                        source=EventSource.MUX,
                        payload={"input_name": "alarm", "state": value}
                    )
                    self.process_alarm_event(alarm_event)
    
    def sync_keys(self) -> None:
        """Синхронизация ключей с бэкендом."""
        try:
            keys_response = self.backend.get_keys()
            if keys_response.get("status") == "ok":
                self.cache.update_keys(keys_response.get("keys", []))
                log_info("Keys synchronized successfully")
        except Exception as e:
            log_error(f"Keys sync failed: {e}")
    
    def sync_access_list(self) -> None:
        """Синхронизация списков доступа с бэкендом."""
        try:
            access_response = self.backend.get_access_list()
            if access_response.get("status") == "ok":
                self.cache.update(access_response.get("identifiers", []))
                log_info("Access list synchronized successfully")
        except Exception as e:
            log_error(f"Access list sync failed: {e}")
    
    def check_timeouts(self) -> None:
        """Проверка таймаутов (не требуется - basic_business_logic управляет таймингами)."""
        pass
    
    def run(self) -> None:
        """Основной цикл обработки событий."""
        log_info("LGTU Controller started")
        
        last_keys_sync = 0
        last_access_sync = 0
        
        while True:
            event = get_event(self.engine, timeout=0.1)
            
            if event:
                if is_qr_read(event):
                    self.process_qr_event(event)
                elif is_card_read(event):
                    self.process_card_event(event)
                elif is_serial_data(event):
                    self.process_serial_event(event)
                elif is_passage_event(event):
                    self.process_passage_event(event)
                elif is_alarm_event(event):
                    self.process_alarm_event(event)
                elif is_button_1_pressed(event):
                    self.handle_button_1()
                elif is_button_2_pressed(event):
                    self.handle_button_2()
                elif is_button_3_pressed(event):
                    self.handle_button_3()
                elif event.type == EventType.MUX_CHANGED:
                    self.process_mux_event(event)
            
            current_time = time.time()
            
            # Синхронизация ключей каждые сутки
            if current_time - last_keys_sync > 86400:
                self.sync_keys()
                last_keys_sync = current_time
            
            # Синхронизация списков доступа каждые 10 минут
            if current_time - last_access_sync > 600:
                self.sync_access_list()
                last_access_sync = current_time
            
            # Проверка таймаутов
            self.check_timeouts()
