#!/usr/bin/env python3
"""
Скрипт для тестирования всей логики на устройстве с логированием.
Записывает все действия пользователя и сравнивает с ожидаемым поведением.
"""

import logging
import time
import json
from datetime import datetime
from pathlib import Path
from scud_lgtu.infrastructure.bootstrap import build_application
from scud_lgtu.infrastructure.config import load as load_config

# Настройка логирования
log_file = Path("device_test_log.txt")
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class DeviceTester:
    """Тестировщик устройства с логированием всех действий."""
    
    def __init__(self):
        """Инициализировать тестировщик."""
        self.config = load_config()
        self.events_log = []
        self.expected_results = []
        self.test_results = []
        
    def log_action(self, action_type, details):
        """Записать действие пользователя."""
        event = {
            "timestamp": datetime.now().isoformat(),
            "action": action_type,
            "details": details
        }
        self.events_log.append(event)
        logger.info(f"Действие: {action_type} - {details}")
    
    def expect(self, action_type, expected_state):
        """Ожидаемое состояние после действия."""
        self.expected_results.append({
            "action": action_type,
            "expected": expected_state
        })
    
    def verify(self, actual_state):
        """Проверить соответствие ожидаемому состоянию."""
        if self.expected_results:
            expected = self.expected_results[-1]["expected"]
            match = actual_state == expected
            result = {
                "timestamp": datetime.now().isoformat(),
                "expected": expected,
                "actual": actual_state,
                "match": match
            }
            self.test_results.append(result)
            if match:
                logger.info(f"✓ Проверка пройдена: {expected} == {actual_state}")
            else:
                logger.error(f"✗ Проверка не пройдена: ожидается {expected}, получено {actual_state}")
            return match
        return True
    
    def run_test_scenario(self, scenario_name, test_func):
        """Запустить тестовый сценарий."""
        logger.info(f"\n{'='*60}")
        logger.info(f"Сценарий: {scenario_name}")
        logger.info(f"{'='*60}")
        
        self.events_log = []
        self.expected_results = []
        self.test_results = []
        
        try:
            test_func()
            passed = all(r["match"] for r in self.test_results)
            logger.info(f"Сценарий '{scenario_name}': {'ПРОЙДЕН' if passed else 'НЕ ПРОЙДЕН'}")
            return passed
        except Exception as e:
            logger.error(f"Сценарий '{scenario_name}': ОШИБКА - {e}")
            return False
    
    def save_results(self, filename):
        """Сохранить результаты тестов в файл."""
        results = {
            "test_date": datetime.now().isoformat(),
            "events_log": self.events_log,
            "expected_results": self.expected_results,
            "test_results": self.test_results
        }
        with open(filename, "w") as f:
            json.dump(results, f, indent=2)
        logger.info(f"Результаты сохранены в {filename}")


def test_card_valid_pass(tester):
    """Тест: успешный проход по карте."""
    # Имитация приложения
    from scud_lgtu.domain.turnstile import TurnstileState
    from scud_lgtu.domain.services import AccessPolicy, PassageTracker
    from scud_lgtu.domain.events import CardRead, OutputCommandsGenerated
    from scud_lgtu.domain.models import Credential
    from scud_lgtu.domain.enums import TokenTypeEnum
    from scud_lgtu.application.event_bus import EventBus
    from scud_lgtu.application.handlers.card import handle_card_read
    from scud_lgtu.infrastructure.cache.access_cache import LocalAccessCache
    import asyncio
    
    # Настройка
    timings = tester.config.get("timings", {})
    turnstile = TurnstileState(auth_timeout=5.0, timings=timings)
    cache = LocalAccessCache(path=None)
    cache.update({
        "id": [{"type": "cardid", "list": ["1234567890"]}],
        "users": {"1": {"cardid": "1234567890"}}
    })
    access_policy = AccessPolicy(cache=cache)
    passage_tracker = PassageTracker()
    event_bus = EventBus(turnstile=turnstile)
    
    # Создаем event loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    event_bus.set_event_loop(loop)
    
    # Тест
    tester.log_action("card_read", {"card_data": "1234567890", "reader": "Wiegand-1"})
    tester.expect("card_read", "ENTRY_OPEN")
    
    credential = Credential(value="1234567890", type=TokenTypeEnum.CARD)
    event = CardRead(credential=credential, reader_id="Wiegand-1")
    
    loop.run_until_complete(
        handle_card_read(event, turnstile, access_policy, passage_tracker, event_bus)
    )
    
    actual_state = turnstile._current_state.value
    tester.verify(actual_state)
    
    loop.close()


def test_card_invalid_deny(tester):
    """Тест: отказ в доступе по карте."""
    from scud_lgtu.domain.turnstile import TurnstileState
    from scud_lgtu.domain.services import AccessPolicy, PassageTracker
    from scud_lgtu.domain.events import CardRead
    from scud_lgtu.domain.models import Credential
    from scud_lgtu.domain.enums import TokenTypeEnum
    from scud_lgtu.application.event_bus import EventBus
    from scud_lgtu.application.handlers.card import handle_card_read
    from scud_lgtu.infrastructure.cache.access_cache import LocalAccessCache
    import asyncio
    
    timings = tester.config.get("timings", {})
    turnstile = TurnstileState(auth_timeout=5.0, timings=timings)
    cache = LocalAccessCache(path=None)
    access_policy = AccessPolicy(cache=cache)
    passage_tracker = PassageTracker()
    event_bus = EventBus(turnstile=turnstile)
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    event_bus.set_event_loop(loop)
    
    tester.log_action("card_read", {"card_data": "0000000000", "reader": "Wiegand-1"})
    tester.expect("card_read", "IDLE")
    
    credential = Credential(value="0000000000", type=TokenTypeEnum.CARD)
    event = CardRead(credential=credential, reader_id="Wiegand-1")
    
    loop.run_until_complete(
        handle_card_read(event, turnstile, access_policy, passage_tracker, event_bus)
    )
    
    actual_state = turnstile._current_state.value
    tester.verify(actual_state)
    
    loop.close()


def test_button_open_entry(tester):
    """Тест: открытие на вход кнопкой."""
    from scud_lgtu.domain.turnstile import TurnstileState
    from scud_lgtu.domain.events import ButtonPressed
    from scud_lgtu.application.event_bus import EventBus
    from scud_lgtu.application.handlers.button import handle_button_pressed
    
    timings = tester.config.get("timings", {})
    turnstile = TurnstileState(auth_timeout=5.0, timings=timings)
    event_bus = EventBus(turnstile=turnstile)
    
    tester.log_action("button_press", {"button": "button_1", "state": False})
    tester.expect("button_press", "ENTRY_OPEN")
    
    event = ButtonPressed(button_id="button_1", state=False)
    handle_button_pressed(event, turnstile, event_bus)
    
    actual_state = turnstile._current_state.value
    tester.verify(actual_state)


def test_button_open_exit(tester):
    """Тест: открытие на выход кнопкой."""
    from scud_lgtu.domain.turnstile import TurnstileState
    from scud_lgtu.domain.events import ButtonPressed
    from scud_lgtu.application.event_bus import EventBus
    from scud_lgtu.application.handlers.button import handle_button_pressed
    
    timings = tester.config.get("timings", {})
    turnstile = TurnstileState(auth_timeout=5.0, timings=timings)
    event_bus = EventBus(turnstile=turnstile)
    
    tester.log_action("button_press", {"button": "button_2", "state": False})
    tester.expect("button_press", "EXIT_OPEN")
    
    event = ButtonPressed(button_id="button_2", state=False)
    handle_button_pressed(event, turnstile, event_bus)
    
    actual_state = turnstile._current_state.value
    tester.verify(actual_state)


def test_alarm_activate(tester):
    """Тест: активация тревоги."""
    from scud_lgtu.domain.turnstile import TurnstileState
    from scud_lgtu.domain.events import AlarmChanged
    from scud_lgtu.application.event_bus import EventBus
    from scud_lgtu.application.handlers.alarm import handle_alarm_changed
    
    timings = tester.config.get("timings", {})
    turnstile = TurnstileState(auth_timeout=5.0, timings=timings)
    event_bus = EventBus(turnstile=turnstile)
    
    tester.log_action("alarm_activate", {"active": True})
    tester.expect("alarm_activate", "ALARM")
    
    event = AlarmChanged(active=True)
    handle_alarm_changed(event, turnstile, event_bus)
    
    actual_state = turnstile._current_state.value
    tester.verify(actual_state)


def test_alarm_deactivate(tester):
    """Тест: деактивация тревоги."""
    from scud_lgtu.domain.turnstile import TurnstileState
    from scud_lgtu.domain.events import AlarmChanged
    from scud_lgtu.application.event_bus import EventBus
    from scud_lgtu.application.handlers.alarm import handle_alarm_changed
    
    timings = tester.config.get("timings", {})
    turnstile = TurnstileState(auth_timeout=5.0, timings=timings)
    turnstile._current_state = turnstile._current_state.__class__.ALARM
    event_bus = EventBus(turnstile=turnstile)
    
    tester.log_action("alarm_deactivate", {"active": False})
    tester.expect("alarm_deactivate", "IDLE")
    
    event = AlarmChanged(active=False)
    handle_alarm_changed(event, turnstile, event_bus)
    
    actual_state = turnstile._current_state.value
    tester.verify(actual_state)


def test_passage_in(tester):
    """Тест: проход на вход."""
    from scud_lgtu.domain.turnstile import TurnstileState
    from scud_lgtu.domain.services import PassageTracker
    from scud_lgtu.domain.events import PassageDetected
    from scud_lgtu.application.event_bus import EventBus
    from scud_lgtu.application.handlers.passage import handle_passage_detected
    from scud_lgtu.infrastructure.persistence.event_store import EventStore
    from scud_lgtu.infrastructure.persistence.event_log import EventLogAdapter
    import asyncio
    
    timings = tester.config.get("timings", {})
    turnstile = TurnstileState(auth_timeout=5.0, timings=timings)
    turnstile._current_state = turnstile._current_state.__class__.ENTRY_OPEN
    passage_tracker = PassageTracker()
    event_bus = EventBus(turnstile=turnstile)
    store = EventStore()
    event_log = EventLogAdapter(store)
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    tester.log_action("passage", {"direction": "in", "zone": "zone1", "duration": 1.5})
    tester.expect("passage", "IDLE")
    
    event = PassageDetected(direction="in", zone="zone1", duration=1.5, token="test_token")
    
    loop.run_until_complete(
        handle_passage_detected(event, turnstile, passage_tracker, event_bus, event_log)
    )
    
    actual_state = turnstile._current_state.value
    tester.verify(actual_state)
    
    loop.close()


def test_alarm_ignores_card(tester):
    """Тест: тревога игнорирует карты."""
    from scud_lgtu.domain.turnstile import TurnstileState
    from scud_lgtu.domain.services import AccessPolicy, PassageTracker
    from scud_lgtu.domain.events import CardRead
    from scud_lgtu.domain.models import Credential
    from scud_lgtu.domain.enums import TokenTypeEnum
    from scud_lgtu.application.event_bus import EventBus
    from scud_lgtu.application.handlers.card import handle_card_read
    from scud_lgtu.infrastructure.cache.access_cache import LocalAccessCache
    import asyncio
    
    timings = tester.config.get("timings", {})
    turnstile = TurnstileState(auth_timeout=5.0, timings=timings)
    turnstile._current_state = turnstile._current_state.__class__.ALARM
    cache = LocalAccessCache(path=None)
    access_policy = AccessPolicy(cache=cache)
    passage_tracker = PassageTracker()
    event_bus = EventBus(turnstile=turnstile)
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    event_bus.set_event_loop(loop)
    
    tester.log_action("card_read_during_alarm", {"card_data": "1234567890"})
    tester.expect("card_read_during_alarm", "ALARM")
    
    credential = Credential(value="1234567890", type=TokenTypeEnum.CARD)
    event = CardRead(credential=credential, reader_id="Wiegand-1")
    
    loop.run_until_complete(
        handle_card_read(event, turnstile, access_policy, passage_tracker, event_bus)
    )
    
    actual_state = turnstile._current_state.value
    tester.verify(actual_state)
    
    loop.close()


def main():
    """Запустить все тесты."""
    logger.info("Начало тестирования устройства")
    logger.info(f"Лог-файл: {log_file}")
    
    tester = DeviceTester()
    
    # Запуск всех тестов
    scenarios = [
        ("Карта: успешный проход", test_card_valid_pass),
        ("Карта: отказ в доступе", test_card_invalid_deny),
        ("Кнопка: открытие на вход", test_button_open_entry),
        ("Кнопка: открытие на выход", test_button_open_exit),
        ("Тревога: активация", test_alarm_activate),
        ("Тревога: деактивация", test_alarm_deactivate),
        ("Проход: вход", test_passage_in),
        ("Тревога: игнорирование карт", test_alarm_ignores_card),
    ]
    
    results = []
    for name, test_func in scenarios:
        passed = tester.run_test_scenario(name, test_func)
        results.append((name, passed))
        time.sleep(0.5)  # Пауза между тестами
    
    # Итоги
    logger.info(f"\n{'='*60}")
    logger.info("ИТОГИ ТЕСТИРОВАНИЯ")
    logger.info(f"{'='*60}")
    
    for name, passed in results:
        status = "✓ ПРОЙДЕН" if passed else "✗ НЕ ПРОЙДЕН"
        logger.info(f"{name}: {status}")
    
    total = len(results)
    passed = sum(1 for _, p in results if p)
    logger.info(f"\nВсего: {total}, Пройдено: {passed}, Не пройдено: {total - passed}")
    
    # Сохранение результатов
    results_file = f"device_test_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    tester.save_results(results_file)
    
    logger.info(f"Тестирование завершено. Результаты в {results_file}")


if __name__ == "__main__":
    main()
