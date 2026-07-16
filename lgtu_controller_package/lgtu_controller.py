"""
Модуль контроллера турникета ЛГТУ для системы управления доступом.
Реализует логику обработки QR-кодов, карт МИР, проходов и пожарной сигнализации.
"""

import time
import logging
from typing import Optional

from .data_types import ScudEvent, EventType
from .basic_business_logic import (
    get_event, is_qr_read, is_card_read, is_passage_event, is_alarm_event,
    is_button_1_pressed, is_button_2_pressed, is_button_3_pressed,
    get_passage_direction, is_passage_in, is_passage_out, is_blockage,
    check_qr_access, check_card_access, grant_access, deny_access,
    authorize_passage, check_authorization, mark_auth_used,
    log_passage, log_error, log_info,
    open_turnstile, close_turnstile, flash_indicator, turn_off_indicator,
    set_green_indicator, set_red_indicator, beep_sequence, beep_repeat,
    set_indicator_with_timeout, set_shift_pins
)

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
    
    def process_qr_event(self, event: ScudEvent) -> None:
        """Обработка QR-кода (валидация уже реализована в декодере)."""
        qr_data = event.payload.get("qr_data")
        if not qr_data:
            deny_access(self.engine)
            log_error("QR event: no data")
            return
        
        # Декодер уже выполнил валидацию подписи Ed25519 и расшифровку payload
        max_id = event.payload.get("max_id")
        if not max_id:
            deny_access(self.engine)
            log_error("QR event: no max_id in payload")
            return
        
        allowed, user_id = check_qr_access(self.cache, str(max_id))
        if allowed:
            # Создаем авторизацию для входа (по умолчанию)
            self.auth_state = authorize_passage("in", "maxid", str(max_id), user_id)
            # Индикация успешной авторизации
            set_green_indicator(self.engine, "w1")
            beep_sequence(self.engine, count=1)
            log_info(f"QR authorized for {max_id}")
        else:
            deny_access(self.engine)
            self.event_counter = log_passage(self.store, self.event_counter, "denied", str(max_id), None, "QR access denied")
    
    def process_card_event(self, event: ScudEvent) -> None:
        """Обработка карты МИР с учетом шифрования считывателем."""
        card_uid = event.payload.get("card_uid")
        if not card_uid:
            deny_access(self.engine)
            log_error("Card event: no UID")
            return
        
        # Проверяем, зашифрован ли UID считывателем
        is_encrypted = event.payload.get("encrypted", False)
        
        if is_encrypted:
            # Считыватель сам зашифровал данные, сравниваем напрямую с таблицей разрешенных
            card_id = card_uid
        else:
            # Считыватель не шифрует, шифруем PAN сами
            # TODO: Реализовать HMAC шифрование PAN
            card_id = self.encrypt_card_pan(card_uid)
        
        allowed, user_id = check_card_access(self.cache, card_id)
        if allowed:
            # Создаем авторизацию для входа (по умолчанию)
            self.auth_state = authorize_passage("in", "cardid", card_id, user_id)
            # Индикация успешной авторизации
            set_green_indicator(self.engine, "w1")
            beep_sequence(self.engine, count=1)
            log_info(f"Card authorized for {card_id}")
        else:
            deny_access(self.engine)
            self.event_counter = log_passage(self.store, self.event_counter, "denied", card_id, None, "Card access denied")
    
    def encrypt_card_pan(self, pan: str) -> str:
        """Шифрование PAN карты для сравнения с таблицей разрешенных."""
        # TODO: Реализовать HMAC_SHA256(HMAC_SHA256(SHA256(PAN), STATIC_KEY), DYNAMIC_KEY)
        # Временно возвращаем PAN как есть
        return pan
    
    def process_passage_event(self, event: ScudEvent) -> None:
        """Обработка события прохода через турникет от датчиков."""
        direction = get_passage_direction(event)
        
        if is_passage_in(event):
            # Датчики зафиксировали вход - проверяем авторизацию и помечаем как завершенный
            self.handle_passage_in(event)
            self.mark_passage_completed("in")
        elif is_passage_out(event):
            # Датчики зафиксировали выход - проверяем авторизацию и помечаем как завершенный
            self.handle_passage_out(event)
            self.mark_passage_completed("out")
        elif is_blockage(event):
            self.handle_blockage(event)
    
    def mark_passage_completed(self, direction: str) -> None:
        """Пометить последний проход как завершенный (датчики зафиксировали проход)."""
        # Находим токен из последней авторизации
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
        
        # Проверка на двойной проход (если человек уже прошел)
        if self.is_double_pass(token, "in"):
            deny_access(self.engine)
            # Тройной бип на BUZ + красный индикатор на 1 секунду
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
        
        # Проверка на двойной проход (если человек уже прошел)
        if self.is_double_pass(token, "out"):
            deny_access(self.engine)
            # Тройной бип на BUZ + красный индикатор на 1 секунду
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
        
        # Если человек уже прошел в этом направлении
        if last_passage["direction"] == direction and last_passage["passed"]:
            return True
        
        return False
    
    def handle_blockage(self, event: ScudEvent) -> None:
        """Обработка заслона."""
        deny_access(self.engine)
        beep_sequence(self.engine, count=3)
        self.event_counter = log_passage(self.store, self.event_counter, "denied", "", None, "Blockage detected")
    
    def process_alarm_event(self, event: ScudEvent) -> None:
        """Обработка события пожарной сигнализации (с инверсией)."""
        # Используем существующую функцию is_alarm_active
        # Для инвертированной тревоги инвертируем результат
        alarm_active = is_alarm_active(event)
        
        # Инвертированная логика: is_alarm_active возвращает True при state == False
        # Для нас state == False (замкнуто) - норма, state == True (разомкнуто) - пожар
        if not alarm_active:  # state == True (разомкнуто) - пожарная тревога активна
            if not self.alarm_active:
                self.alarm_active = True
                open_turnstile(self.engine)
                # Мигающий красный индикатор + пищание BUZ и считывателей
                self.start_alarm_indication()
                log_error("Fire alarm active - turnstile unlocked")
        else:  # state == False (замкнуто) - нормальное состояние
            if self.alarm_active:
                self.alarm_active = False
                close_turnstile(self.engine)
                self.stop_alarm_indication()
                log_info("Fire alarm cleared - turnstile locked")
    
    def start_alarm_indication(self) -> None:
        """Запустить индикацию пожарной тревоги (мигающий красный + пищание)."""
        # Запускаем в отдельном потоке для неблокирующей работы
        import threading
        self.alarm_thread = threading.Thread(target=self._alarm_indication_loop, daemon=True)
        self.alarm_thread.start()
    
    def stop_alarm_indication(self) -> None:
        """Остановить индикацию пожарной тревоги."""
        self.alarm_active = False
        turn_off_indicator(self.engine, "w1", "red")
        # Выключаем пищалки
        set_shift_pins(self.engine, {"buz": False, "w1_beep": False, "w2_beep": False})
    
    def _alarm_indication_loop(self) -> None:
        """Цикл индикации пожарной тревоги."""
        while self.alarm_active:
            # Мигающий красный индикатор
            set_shift_pins(self.engine, {"w1_red": True})
            # Пищание BUZ и считывателей
            set_shift_pins(self.engine, {"buz": True, "w1_beep": True, "w2_beep": True})
            time.sleep(0.5)
            
            if not self.alarm_active:
                break
                
            set_shift_pins(self.engine, {"w1_red": False})
            set_shift_pins(self.engine, {"buz": False, "w1_beep": False, "w2_beep": False})
            time.sleep(0.5)
    
    def handle_button_1(self) -> None:
        """Обработка кнопки 1 - открыть на вход."""
        # Создаем авторизацию для входа
        self.auth_state = authorize_passage("in", "button", "button_1", None)
        open_turnstile(self.engine)
        set_green_indicator(self.engine, "w1")
        beep_sequence(self.engine, count=1)
        log_info("Button 1: open for entry")
    
    def handle_button_2(self) -> None:
        """Обработка кнопки 2 - открыть на выход."""
        # Создаем авторизацию для выхода
        self.auth_state = authorize_passage("out", "button", "button_2", None)
        open_turnstile(self.engine)
        set_green_indicator(self.engine, "w1")
        beep_sequence(self.engine, count=1)
        log_info("Button 2: open for exit")
    
    def handle_button_3(self) -> None:
        """Обработка кнопки 3 - не используется."""
        # Кнопка 3 пока не используется
        pass
    
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
