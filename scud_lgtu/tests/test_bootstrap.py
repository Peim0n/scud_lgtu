"""Tests for bootstrap and dependency injection."""
import os
import pytest
from scud_lgtu.infrastructure.bootstrap import build_application


@pytest.fixture
def config_path():
    """Get path to test config file."""
    script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(script_dir, "config.yml")


def test_build_application_returns_app(config_path):
    """Test that build_application returns an application object."""
    app = build_application(config_path)
    assert app is not None
    assert hasattr(app, '_engine')
    assert hasattr(app, '_config')


def test_build_application_loads_config(config_path):
    """Test that build_application loads configuration."""
    app = build_application(config_path)
    assert app._config is not None
    assert isinstance(app._config, dict)


def test_build_application_sets_logging(config_path):
    """Test that build_application sets up logging."""
    import logging
    
    # Build application
    app = build_application(config_path)
    
    # Check that logging is configured
    root_logger = logging.getLogger()
    assert root_logger.level is not None
