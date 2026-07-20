"""Tests for LGTUController with mock hardware."""
import pytest
from unittest.mock import Mock, MagicMock, patch
from scud_lgtu.application.controllers.lgtu_controller import LGTUController
from scud_lgtu.infrastructure.persistence.event_store import ScudEvent, EventType, EventSource


@pytest.fixture
def mock_engine():
    """Mock ScudEngine."""
    engine = Mock()
    engine.get_event_queue = Mock()
    return engine


@pytest.fixture
def mock_cache():
    """Mock LocalAccessCache."""
    cache = Mock()
    cache.is_allowed = Mock(return_value=(True, 1))
    cache.count = Mock(return_value=0)
    return cache


@pytest.fixture
def mock_store():
    """Mock EventStore."""
    store = Mock()
    store.append = Mock()
    store.flush = Mock(return_value=[])
    return store


@pytest.fixture
def mock_backend():
    """Mock BackendClient."""
    backend = Mock()
    backend.is_online = Mock(return_value=False)
    backend.get_access_list = Mock(return_value={})
    backend.get_keys = Mock(return_value={"status": "ok", "keys": []})
    return backend


@pytest.fixture
def mock_config():
    """Mock configuration."""
    return {
        "timings": {
            "auth_timeout_s": 30.0,
            "button_timer_duration_s": 2.0,
        }
    }


@pytest.fixture
def mock_qr_decoder():
    """Mock QRDecoder."""
    decoder = Mock()
    decoder.decode_url = Mock(return_value={"max_id": "12345"})
    return decoder


@pytest.fixture
def controller(mock_engine, mock_cache, mock_store, mock_backend, mock_config, mock_qr_decoder):
    """Create LGTUController with mocked dependencies."""
    with patch('scud_lgtu.application.controllers.lgtu_controller.QRDecoder', return_value=mock_qr_decoder):
        ctrl = LGTUController(mock_engine, mock_cache, mock_store, mock_backend, mock_config)
        return ctrl


def test_controller_initialization(controller):
    """Test that controller initializes correctly."""
    assert controller.engine is not None
    assert controller.cache is not None
    assert controller.store is not None
    assert controller.backend is not None
    assert controller.config is not None
    assert controller.event_counter == 0
    assert controller.auth_state is None
    assert controller.alarm_active is False
    assert controller.auth_timeout == 30.0


@patch('scud_lgtu.application.controllers.lgtu_controller.check_qr_access')
def test_process_qr_event_allowed(mock_check_qr, controller, mock_cache):
    """Test processing QR event when access is allowed."""
    # Setup mock check_qr_access to return allowed
    mock_check_qr.return_value = (True, 123)
    
    # Create QR event
    event = ScudEvent(
        type=EventType.QR_READ,
        source=EventSource.SERIAL,
        payload={
            "qr_data": "https://pass.lipetsk.ru/test",
            "max_id": "12345"
        }
    )
    
    # Process event
    controller.process_qr_event(event)
    
    # Check that check_qr_access was called
    mock_check_qr.assert_called_once()
    
    # Check that auth state was set
    assert controller.auth_state is not None
    assert controller.auth_state["token"] == "12345"
    assert controller.auth_state["user_id"] == 123


@patch('scud_lgtu.application.controllers.lgtu_controller.check_qr_access')
def test_process_qr_event_denied(mock_check_qr, controller, mock_cache):
    """Test processing QR event when access is denied."""
    # Setup mock check_qr_access to return denied
    mock_check_qr.return_value = (False, None)
    
    # Create QR event
    event = ScudEvent(
        type=EventType.QR_READ,
        source=EventSource.SERIAL,
        payload={
            "qr_data": "https://pass.lipetsk.ru/test",
            "max_id": "12345"
        }
    )
    
    # Process event
    controller.process_qr_event(event)
    
    # Check that check_qr_access was called
    mock_check_qr.assert_called_once()
    
    # Check that auth state was not set
    assert controller.auth_state is None


def test_process_qr_event_no_max_id(controller):
    """Test processing QR event without max_id."""
    # Create QR event without max_id
    event = ScudEvent(
        type=EventType.QR_READ,
        source=EventSource.SERIAL,
        payload={
            "qr_data": "https://pass.lipetsk.ru/test"
        }
    )
    
    # Process event
    controller.process_qr_event(event)
    
    # Check that auth state was not set
    assert controller.auth_state is None


def test_process_card_event_allowed(controller, mock_cache):
    """Test processing card event when access is allowed."""
    # Setup mock cache to return allowed
    mock_cache.is_allowed = Mock(return_value=(True, 456))
    
    # Create card event
    event = ScudEvent(
        type=EventType.CARD_READ,
        source=EventSource.WIEGAND,
        payload={
            "card_data": "1234567890",
            "is_valid": True,
            "encrypted": False
        }
    )
    
    # Process event
    controller.process_card_event(event)
    
    # Check that cache was queried
    mock_cache.is_allowed.assert_called_once()
    
    # Check that auth state was set
    assert controller.auth_state is not None
    assert controller.auth_state["token"] == "1234567890"
    assert controller.auth_state["user_id"] == 456


def test_process_card_event_invalid(controller):
    """Test processing invalid card event."""
    # Create invalid card event
    event = ScudEvent(
        type=EventType.CARD_READ,
        source=EventSource.WIEGAND,
        payload={
            "card_data": "1234567890",
            "is_valid": False,
            "error_message": "Invalid card"
        }
    )
    
    # Process event
    controller.process_card_event(event)
    
    # Check that auth state was not set
    assert controller.auth_state is None


def test_encrypt_card_pan(controller):
    """Test card PAN encryption (should return as-is)."""
    pan = "1234567890123456"
    encrypted = controller.encrypt_card_pan(pan)
    # Readers handle encryption, so controller returns as-is
    assert encrypted == pan


def test_process_passage_event_in(controller):
    """Test processing passage IN event."""
    # Set auth state with recent time
    import time
    controller.auth_state = {
        "token": "test_token",
        "user_id": 1,
        "direction": "in",
        "used": False,
        "time": time.time()  # Current time
    }
    
    # Create passage event
    event = ScudEvent(
        type=EventType.INPUT_SIGNAL,
        source=EventSource.MUX,
        payload={
            "zone": "zone1",
            "direction": "in",
            "duration": 1.0
        }
    )
    
    # Process event
    controller.process_passage_event(event)
    
    # Check that passage was marked
    assert "test_token" in controller.last_passages


def test_process_passage_event_out(controller):
    """Test processing passage OUT event."""
    # Set auth state with recent time
    import time
    controller.auth_state = {
        "token": "test_token",
        "user_id": 1,
        "direction": "out",
        "used": False,
        "time": time.time()  # Current time
    }
    
    # Create passage event
    event = ScudEvent(
        type=EventType.INPUT_SIGNAL,
        source=EventSource.MUX,
        payload={
            "zone": "zone1",
            "direction": "out",
            "duration": 1.0
        }
    )
    
    # Process event
    controller.process_passage_event(event)
    
    # Check that passage was marked
    assert "test_token" in controller.last_passages


def test_is_double_pass(controller):
    """Test double pass detection."""
    # Add first passage
    controller.last_passages["token1"] = {"direction": "in", "passed": True}
    
    # Check for double pass
    assert controller.is_double_pass("token1", "in") is True
    
    # Check for different direction
    assert controller.is_double_pass("token1", "out") is False
    
    # Check for new token
    assert controller.is_double_pass("token2", "in") is False


def test_process_alarm_event_activate(controller):
    """Test alarm activation."""
    # Create alarm event with active state
    event = ScudEvent(
        type=EventType.INPUT_SIGNAL,
        source=EventSource.MUX,
        payload={
            "state": 1  # Active
        }
    )
    
    # Process event
    controller.process_alarm_event(event)
    
    # Check that alarm is active
    assert controller.alarm_active is True


def test_process_alarm_event_deactivate(controller):
    """Test alarm deactivation."""
    # Set alarm as active
    controller.alarm_active = True
    
    # Create alarm event with inactive state
    event = ScudEvent(
        type=EventType.INPUT_SIGNAL,
        source=EventSource.MUX,
        payload={
            "state": 0  # Inactive
        }
    )
    
    # Process event
    controller.process_alarm_event(event)
    
    # Check that alarm is inactive
    assert controller.alarm_active is False


def test_handle_button_1(controller):
    """Test button 1 handling."""
    # Handle button 1
    controller.handle_button_1()
    
    # Check that relay and indicator were set
    assert controller._active_relay == "rel1"
    assert controller._active_indicator == "w1_green"


def test_handle_button_2(controller):
    """Test button 2 handling."""
    # Handle button 2
    controller.handle_button_2()
    
    # Check that relay and indicator were set
    assert controller._active_relay == "rel2"
    assert controller._active_indicator == "w2_green"


def test_handle_button_3(controller):
    """Test button 3 handling (should do nothing)."""
    # Handle button 3 - should not raise
    controller.handle_button_3()


def test_process_mux_event_button_1_press(controller):
    """Test MUX event for button 1 press."""
    # Initialize last_mux_state
    controller.last_mux_state = {"button_1": 1}  # Previous state
    
    # Create MUX event with button 1 press
    event = ScudEvent(
        type=EventType.MUX_CHANGED,
        source=EventSource.MUX,
        payload={
            "states": {
                "button_1": 0  # Pressed
            }
        }
    )
    
    # Process event
    controller.process_mux_event(event)
    
    # Check that button was handled
    assert controller._active_relay == "rel1"


def test_process_mux_event_button_2_press(controller):
    """Test MUX event for button 2 press."""
    # Initialize last_mux_state
    controller.last_mux_state = {"button_2": 1}  # Previous state
    
    # Create MUX event with button 2 press
    event = ScudEvent(
        type=EventType.MUX_CHANGED,
        source=EventSource.MUX,
        payload={
            "states": {
                "button_2": 0  # Pressed
            }
        }
    )
    
    # Process event
    controller.process_mux_event(event)
    
    # Check that button was handled
    assert controller._active_relay == "rel2"


def test_process_mux_event_alarm(controller):
    """Test MUX event for alarm."""
    # Initialize last_mux_state
    controller.last_mux_state = {"alarm": 0}  # Previous state
    
    # Create MUX event with alarm
    event = ScudEvent(
        type=EventType.MUX_CHANGED,
        source=EventSource.MUX,
        payload={
            "states": {
                "alarm": 1  # Active
            }
        }
    )
    
    # Process event
    controller.process_mux_event(event)
    
    # Check that alarm is active
    assert controller.alarm_active is True


def test_sync_keys(controller, mock_backend):
    """Test keys synchronization."""
    # Setup mock backend
    mock_backend.get_keys = Mock(return_value={"status": "ok", "keys": ["key1", "key2"]})
    
    # Sync keys
    controller.sync_keys()
    
    # Check that backend was called
    mock_backend.get_keys.assert_called_once()
    
    # Check that cache was updated
    mock_cache = controller.cache
    if hasattr(mock_cache, 'update_keys'):
        mock_cache.update_keys.assert_called_once_with(["key1", "key2"])


def test_sync_access_list(controller, mock_backend):
    """Test access list synchronization."""
    # Setup mock backend
    mock_backend.get_access_list = Mock(return_value={
        "status": "ok",
        "identifiers": ["id1", "id2"]
    })
    
    # Sync access list
    controller.sync_access_list()
    
    # Check that backend was called
    mock_backend.get_access_list.assert_called_once()
    
    # Check that cache was updated
    controller.cache.update.assert_called_once()


def test_mark_passage_completed(controller):
    """Test marking passage as completed."""
    # Add passage
    controller.last_passages["token1"] = {"direction": "in", "passed": False}
    
    # Mark as completed
    controller.mark_passage_completed("in")
    
    # Check that passage is marked
    assert controller.last_passages["token1"]["passed"] is True
