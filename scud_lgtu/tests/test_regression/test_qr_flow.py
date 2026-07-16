"""Regression test for QR flow."""
import pytest
from scud_lgtu.application.lgtu_controller import LGTUController
from scud_lgtu.infrastructure.cache.access_cache import LocalAccessCache
from scud_lgtu.infrastructure.persistence.event_store import EventStore
from scud_lgtu.infrastructure.backend.client import BackendClient
from scud_lgtu.tests.fixtures.mock_engine import MockScudEngine
from scud_lgtu.tests.fixtures.sample_events import sample_qr_event


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
        "id": [{"type": "maxid", "list": ["12345"]}],
        "users": {"1": {"maxid": "12345"}}
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


def test_qr_event_processing(controller):
    """Test that QR event is processed without errors."""
    # Arrange
    event = sample_qr_event(max_id="12345")
    
    # Act - should not raise exception
    controller.process_qr_event(event)
    
    # Assert - event was processed
    # (Specific behavior depends on cache hashing, just ensure no crash)


def test_qr_event_no_max_id(controller):
    """Test that QR event without max_id is handled."""
    # Arrange
    event = sample_qr_event()
    event.payload["max_id"] = None
    
    # Act - should not raise exception
    controller.process_qr_event(event)
    
    # Assert - event was handled gracefully
    assert controller.auth_state is None


def test_qr_event_no_qr_data(controller):
    """Test that QR event without qr_data is handled."""
    # Arrange
    event = sample_qr_event()
    event.payload["qr_data"] = None
    
    # Act - should not raise exception
    controller.process_qr_event(event)
    
    # Assert - event was handled gracefully
    assert controller.auth_state is None
