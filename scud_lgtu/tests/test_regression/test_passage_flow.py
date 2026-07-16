"""Regression test for passage flow."""
import pytest
from scud_lgtu.application.lgtu_controller import LGTUController
from scud_lgtu.infrastructure.cache.access_cache import LocalAccessCache
from scud_lgtu.infrastructure.persistence.event_store import EventStore
from scud_lgtu.infrastructure.backend.client import BackendClient
from scud_lgtu.tests.fixtures.mock_engine import MockScudEngine
from scud_lgtu.tests.fixtures.sample_events import sample_mux_event


@pytest.fixture
def mock_engine():
    """Create a mock engine."""
    return MockScudEngine()


@pytest.fixture
def mock_cache():
    """Create a mock cache."""
    return LocalAccessCache(path=None)


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


def test_mux_event_processing(controller):
    """Test that mux event is processed without errors."""
    # Arrange
    event = sample_mux_event(input_name="button_1", state=0)
    
    # Act - should not raise exception
    controller.process_mux_event(event)
    
    # Assert - event was processed
    # (Specific behavior depends on mux configuration, just ensure no crash)
