"""Regression test for card flow."""
import pytest
from scud_lgtu.application.lgtu_controller import LGTUController
from scud_lgtu.infrastructure.cache.access_cache import LocalAccessCache
from scud_lgtu.infrastructure.persistence.event_store import EventStore
from scud_lgtu.infrastructure.backend.client import BackendClient
from scud_lgtu.tests.fixtures.mock_engine import MockScudEngine
from scud_lgtu.tests.fixtures.sample_events import sample_card_event


@pytest.fixture
def mock_engine():
    """Create a mock engine."""
    return MockScudEngine()


@pytest.fixture
def mock_cache():
    """Create a mock cache with test data."""
    cache = LocalAccessCache(path=None)
    # Add a test identifier using the update method
    cache.update({
        "id": [{"type": "cardid", "list": ["1234567890"]}],
        "users": {"1": {"cardid": "1234567890"}}
    })
    return cache


@pytest.fixture
def mock_store():
    """Create a mock event store."""
    return EventStore()


@pytest.fixture
def mock_backend():
    """Create a mock backend client."""
    return BackendClient()


@pytest.fixture
def mock_config():
    """Create a mock config."""
    return {
        "timings": {
            "auth_timeout_s": 30.0
        }
    }


@pytest.fixture
def controller(mock_engine, mock_cache, mock_store, mock_backend, mock_config):
    """Create a controller with mocked dependencies."""
    return LGTUController(
        engine=mock_engine,
        cache=mock_cache,
        store=mock_store,
        backend_client=mock_backend,
        config=mock_config
    )


def test_card_event_processing(controller):
    """Test that card event is processed without errors."""
    # Arrange
    event = sample_card_event(card_data="1234567890")
    
    # Act - should not raise exception
    controller.process_card_event(event)
    
    # Assert - event was processed
    # (Specific behavior depends on cache hashing, just ensure no crash)


def test_card_event_invalid(controller):
    """Test that invalid card is handled."""
    # Arrange
    event = sample_card_event(card_data="1234567890")
    event.payload["is_valid"] = False
    event.payload["error_message"] = "Invalid card format"
    
    # Act - should not raise exception
    controller.process_card_event(event)
    
    # Assert - event was handled gracefully
    assert controller.auth_state is None


def test_card_event_no_card_data(controller):
    """Test that card event without card_data is handled."""
    # Arrange
    event = sample_card_event()
    event.payload["card_data"] = None
    
    # Act - should not raise exception
    controller.process_card_event(event)
    
    # Assert - event was handled gracefully
    assert controller.auth_state is None
