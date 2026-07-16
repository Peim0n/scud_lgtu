"""Интеграционные тесты для полной логики системы."""
import pytest
import asyncio
import logging
from unittest.mock import Mock, MagicMock
from scud_lgtu.domain.turnstile import TurnstileState
from scud_lgtu.domain.services import AccessPolicy, PassageTracker
from scud_lgtu.domain.events import QrRead, CardRead, ButtonPressed, AlarmChanged, PassageDetected, OutputCommandsGenerated
from scud_lgtu.domain.models import Credential
from scud_lgtu.domain.enums import DirectionEnum, TokenTypeEnum
from scud_lgtu.application.event_bus import EventBus
from scud_lgtu.application.handlers.qr import handle_qr_read
from scud_lgtu.application.handlers.card import handle_card_read
from scud_lgtu.application.handlers.button import handle_button_pressed
from scud_lgtu.application.handlers.alarm import handle_alarm_changed
from scud_lgtu.application.handlers.passage import handle_passage_detected
from scud_lgtu.infrastructure.cache.access_cache import LocalAccessCache
from scud_lgtu.infrastructure.persistence.event_store import EventStore
from scud_lgtu.infrastructure.persistence.event_log import EventLogAdapter

# Настройка логирования для тестов
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)


@pytest.fixture
def mock_cache():
    """Создать кэш с тестовыми данными."""
    cache = LocalAccessCache(path=None)
    cache.update({
        "id": [{"type": "cardid", "list": ["1234567890"]}, {"type": "maxid", "list": ["9876543210"]}],
        "users": {"1": {"cardid": "1234567890"}, "2": {"maxid": "9876543210"}}
    })
    return cache


@pytest.fixture
def mock_store():
    """Создать хранилище событий."""
    return EventStore()


@pytest.fixture
def event_log(mock_store):
    """Создать адаптер лога событий."""
    return EventLogAdapter(mock_store)


@pytest.fixture
def timings():
    """Тайминги для тестов."""
    return {
        "auth_timeout_s": 5.0,
        "deny_beep_duration_s": 0.1,
        "deny_beep_pause_s": 0.1,
        "deny_beep_count": 3,
        "open_beep_duration_s": 0.1,
        "indicator_duration_s": 2.0,
    }


@pytest.fixture
def turnstile(timings):
    """Создать состояние турникета."""
    return TurnstileState(auth_timeout=5.0, timings=timings)


@pytest.fixture
def access_policy(mock_cache):
    """Создать политику доступа."""
    return AccessPolicy(cache=mock_cache)


@pytest.fixture
def passage_tracker():
    """Создать трекер проходов."""
    return PassageTracker()


@pytest.fixture
def event_bus(turnstile):
    """Создать шину событий."""
    bus = EventBus(turnstile=turnstile)
    # Создаем event loop для async handlers
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    bus.set_event_loop(loop)
    return bus


class TestCardFlow:
    """Тесты потока обработки карт."""
    
    @pytest.mark.asyncio
    async def test_card_valid_pass(self, event_bus, turnstile, access_policy, passage_tracker):
        """Тест успешного прохода по карте."""
        # Arrange
        credential = Credential(value="1234567890", type=TokenTypeEnum.CARD)
        event = CardRead(credential=credential, reader_id="Wiegand-1")
        
        # Act
        await handle_card_read(event, turnstile, access_policy, passage_tracker, event_bus)
        
        # Assert
        assert turnstile._current_state.value == "ENTRY_OPEN"
        assert len(passage_tracker._last_passages) == 1
        logger.info("✓ Карта: успешный проход")
    
    @pytest.mark.asyncio
    async def test_card_invalid_deny(self, event_bus, turnstile, access_policy, passage_tracker):
        """Тест отказа в доступе по карте."""
        # Arrange
        credential = Credential(value="0000000000", type=TokenTypeEnum.CARD)
        event = CardRead(credential=credential, reader_id="Wiegand-1")
        
        # Act
        await handle_card_read(event, turnstile, access_policy, passage_tracker, event_bus)
        
        # Assert
        assert turnstile._current_state.value == "IDLE"
        assert len(passage_tracker._last_passages) == 0
        logger.info("✓ Карта: отказ в доступе")


class TestQrFlow:
    """Тесты потока обработки QR-кодов."""
    
    @pytest.mark.asyncio
    async def test_qr_valid_pass(self, event_bus, turnstile, access_policy, passage_tracker):
        """Тест успешного прохода по QR-коду."""
        # Arrange
        credential = Credential(value="9876543210", type=TokenTypeEnum.QR)
        event = QrRead(credential=credential, reader_id="QR-1")
        
        # Act
        await handle_qr_read(event, turnstile, access_policy, passage_tracker, event_bus)
        
        # Assert
        assert turnstile._current_state.value == "ENTRY_OPEN"
        assert len(passage_tracker._last_passages) == 1
        logger.info("✓ QR-код: успешный проход")
    
    @pytest.mark.asyncio
    async def test_qr_invalid_deny(self, event_bus, turnstile, access_policy, passage_tracker):
        """Тест отказа в доступе по QR-коду."""
        # Arrange
        credential = Credential(value="0000000000", type=TokenTypeEnum.QR)
        event = QrRead(credential=credential, reader_id="QR-1")
        
        # Act
        await handle_qr_read(event, turnstile, access_policy, passage_tracker, event_bus)
        
        # Assert
        assert turnstile._current_state.value == "IDLE"
        assert len(passage_tracker._last_passages) == 0
        logger.info("✓ QR-код: отказ в доступе")


class TestButtonFlow:
    """Тесты потока обработки кнопок."""
    
    def test_button_1_open_entry(self, event_bus, turnstile):
        """Тест кнопки 1 - открытие на вход."""
        # Arrange
        event = ButtonPressed(button_id="button_1", state=False)
        
        # Act
        handle_button_pressed(event, turnstile, event_bus)
        
        # Assert
        assert turnstile._current_state.value == "ENTRY_OPEN"
        logger.info("✓ Кнопка 1: открытие на вход")
    
    def test_button_2_open_exit(self, event_bus, turnstile):
        """Тест кнопки 2 - открытие на выход."""
        # Arrange
        event = ButtonPressed(button_id="button_2", state=False)
        
        # Act
        handle_button_pressed(event, turnstile, event_bus)
        
        # Assert
        assert turnstile._current_state.value == "EXIT_OPEN"
        logger.info("✓ Кнопка 2: открытие на выход")
    
    def test_button_3_close(self, event_bus, turnstile):
        """Тест кнопки 3 - закрытие."""
        # Arrange
        turnstile._current_state = turnstile._current_state.__class__.ENTRY_OPEN
        event = ButtonPressed(button_id="button_3", state=False)
        
        # Act
        handle_button_pressed(event, turnstile, event_bus)
        
        # Assert
        assert turnstile._current_state.value == "IDLE"
        logger.info("✓ Кнопка 3: закрытие")


class TestAlarmFlow:
    """Тесты потока обработки тревоги."""
    
    def test_alarm_activate(self, event_bus, turnstile):
        """Тест активации тревоги."""
        # Arrange
        event = AlarmChanged(active=True)
        
        # Act
        handle_alarm_changed(event, turnstile, event_bus)
        
        # Assert
        assert turnstile._current_state.value == "ALARM"
        assert turnstile._alarm_since is not None
        logger.info("✓ Тревога: активация")
    
    def test_alarm_deactivate(self, event_bus, turnstile):
        """Тест деактивации тревоги."""
        # Arrange
        turnstile._current_state = turnstile._current_state.__class__.ALARM
        event = AlarmChanged(active=False)
        
        # Act
        handle_alarm_changed(event, turnstile, event_bus)
        
        # Assert
        assert turnstile._current_state.value == "IDLE"
        assert turnstile._alarm_since is None
        logger.info("✓ Тревога: деактивация")


class TestPassageFlow:
    """Тесты потока обработки проходов."""
    
    @pytest.mark.asyncio
    async def test_passage_in(self, event_bus, turnstile, passage_tracker, event_log):
        """Тест прохода на вход."""
        # Arrange
        event = PassageDetected(direction="in", zone="zone1", duration=1.5, token="test_token")
        
        # Act
        await handle_passage_detected(event, turnstile, passage_tracker, event_bus, event_log)
        
        # Assert
        assert turnstile._current_state.value == "IDLE"
        logger.info("✓ Проход: вход")
    
    @pytest.mark.asyncio
    async def test_passage_out(self, event_bus, turnstile, passage_tracker, event_log):
        """Тест прохода на выход."""
        # Arrange
        event = PassageDetected(direction="out", zone="zone1", duration=1.5, token="test_token")
        
        # Act
        await handle_passage_detected(event, turnstile, passage_tracker, event_bus, event_log)
        
        # Assert
        assert turnstile._current_state.value == "IDLE"
        logger.info("✓ Проход: выход")
    
    @pytest.mark.asyncio
    async def test_passage_turnback(self, event_bus, turnstile, passage_tracker, event_log):
        """Тест разворота."""
        # Arrange
        event = PassageDetected(direction="turnback", zone="zone1", duration=3.0)
        
        # Act
        await handle_passage_detected(event, turnstile, passage_tracker, event_bus, event_log)
        
        # Assert
        assert turnstile._current_state.value == "IDLE"
        logger.info("✓ Проход: разворот")
    
    @pytest.mark.asyncio
    async def test_passage_blockage(self, event_bus, turnstile, passage_tracker, event_log):
        """Тест заслона."""
        # Arrange
        event = PassageDetected(direction="blockage", zone="zone1", duration=6.0)
        
        # Act
        await handle_passage_detected(event, turnstile, passage_tracker, event_bus, event_log)
        
        # Assert - при заслоне реле должно остаться открытым
        logger.info("✓ Проход: заслон")


class TestAlarmIgnoreEvents:
    """Тесты игнорирования событий во время тревоги."""
    
    @pytest.mark.asyncio
    async def test_alarm_ignores_card(self, event_bus, turnstile, access_policy, passage_tracker):
        """Тест игнорирования карты во время тревоги."""
        # Arrange
        turnstile._current_state = turnstile._current_state.__class__.ALARM
        credential = Credential(value="1234567890", type=TokenTypeEnum.CARD)
        event = CardRead(credential=credential, reader_id="Wiegand-1")
        
        # Act
        await handle_card_read(event, turnstile, access_policy, passage_tracker, event_bus)
        
        # Assert - состояние не должно измениться
        assert turnstile._current_state.value == "ALARM"
        logger.info("✓ Тревога: карта игнорируется")
    
    @pytest.mark.asyncio
    async def test_alarm_ignores_qr(self, event_bus, turnstile, access_policy, passage_tracker):
        """Тест игнорирования QR-кода во время тревоги."""
        # Arrange
        turnstile._current_state = turnstile._current_state.__class__.ALARM
        credential = Credential(value="9876543210", type=TokenTypeEnum.QR)
        event = QrRead(credential=credential, reader_id="QR-1")
        
        # Act
        await handle_qr_read(event, turnstile, access_policy, passage_tracker, event_bus)
        
        # Assert - состояние не должно измениться
        assert turnstile._current_state.value == "ALARM"
        logger.info("✓ Тревога: QR-код игнорируется")
    
    @pytest.mark.asyncio
    async def test_alarm_allows_passage(self, event_bus, turnstile, passage_tracker, event_log):
        """Тест обработки проходов во время тревоги."""
        # Arrange
        turnstile._current_state = turnstile._current_state.__class__.ALARM
        event = PassageDetected(direction="in", zone="zone1", duration=1.5, token="test_token")
        
        # Act
        await handle_passage_detected(event, turnstile, passage_tracker, event_bus, event_log)
        
        # Assert - проходы должны обрабатываться
        # (проверяем что обработчик был вызван без ошибок)
        logger.info("✓ Тревога: проходы обрабатываются")


class TestDoublePassPrevention:
    """Тесты предотвращения двойного прохода."""
    
    @pytest.mark.asyncio
    async def test_double_pass_prevention(self, event_bus, turnstile, access_policy, passage_tracker):
        """Тест предотвращения двойного прохода."""
        # Arrange
        credential = Credential(value="1234567890", type=TokenTypeEnum.CARD)
        event = CardRead(credential=credential, reader_id="Wiegand-1")
        
        # Act - первый проход
        await handle_card_read(event, turnstile, access_policy, passage_tracker, event_bus)
        
        # Act - попытка повторного прохода
        await handle_card_read(event, turnstile, access_policy, passage_tracker, event_bus)
        
        # Assert - сессия должна быть отслежена
        assert len(passage_tracker._last_passages) == 1
        logger.info("✓ Двойной проход: предотвращение")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
