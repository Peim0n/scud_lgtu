"""Tests for configuration loading."""
import os
import pytest
from scud_lgtu.infrastructure.config import load


def test_load_config():
    """Test loading configuration from YAML file."""
    # Get path to config file
    script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config_path = os.path.join(script_dir, "config.yml")
    
    # Load config
    config = load(config_path)
    
    # Check that config is a dict
    assert isinstance(config, dict)
    
    # Check required sections
    assert "gpiod_controller" in config
    assert "shift_register" in config
    assert "wiegand" in config
    assert "serial" in config
    assert "timings" in config
    assert "logging" in config


def test_gpio_config():
    """Test GPIO controller configuration."""
    script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config_path = os.path.join(script_dir, "config.yml")
    config = load(config_path)
    
    gpio_config = config["gpiod_controller"]
    assert "pins" in gpio_config
    
    pins = gpio_config["pins"]
    assert "shift_data" in pins
    assert "shift_clk" in pins
    assert "shift_latch" in pins


def test_shift_register_config():
    """Test shift register configuration."""
    script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config_path = os.path.join(script_dir, "config.yml")
    config = load(config_path)
    
    shift_config = config["shift_register"]
    assert "ser_data" in shift_config
    assert "ser_clk" in shift_config
    assert "ser_latch" in shift_config
    assert "reg_len" in shift_config
    assert "pins" in shift_config
    
    assert shift_config["reg_len"] == 16


def test_wiegand_config():
    """Test Wiegand reader configuration."""
    script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config_path = os.path.join(script_dir, "config.yml")
    config = load(config_path)
    
    wiegand_config = config["wiegand"]
    assert isinstance(wiegand_config, list)
    assert len(wiegand_config) > 0


def test_serial_config():
    """Test serial port configuration."""
    script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config_path = os.path.join(script_dir, "config.yml")
    config = load(config_path)
    
    serial_config = config["serial"]
    assert isinstance(serial_config, list)
    assert len(serial_config) > 0


def test_timings_config():
    """Test timings configuration."""
    script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config_path = os.path.join(script_dir, "config.yml")
    config = load(config_path)
    
    timings = config["timings"]
    assert isinstance(timings, dict)
    assert "backend_sync_interval_s" in timings


def test_logging_config():
    """Test logging configuration."""
    script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config_path = os.path.join(script_dir, "config.yml")
    config = load(config_path)
    
    logging_config = config["logging"]
    assert "level" in logging_config
    assert "format" in logging_config
    assert "loggers" in logging_config
