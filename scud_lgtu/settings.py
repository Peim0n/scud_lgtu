"""Settings - typed configuration."""
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class MuxConfig:
    """Multiplexer configuration."""
    addr_pins: Dict[str, int] = field(default_factory=dict)
    addr_labels: List[str] = field(default_factory=list)
    input_pin: str = ""
    poll_interval_ms: float = 50.0


@dataclass
class ShiftConfig:
    """Shift register configuration."""
    ser_data: str = ""
    ser_clk: str = ""
    ser_latch: str = ""
    reg_len: int = 8


@dataclass
class WiegandConfig:
    """Wiegand reader configuration."""
    readers: List[Dict] = field(default_factory=list)
    bit_timeout_ms: float = 5.0


@dataclass
class SerialConfig:
    """Serial port configuration."""
    ports: List[Dict] = field(default_factory=list)
    queue_timeout_s: float = 1.0


@dataclass
class TimingsConfig:
    """Timing configuration."""
    mux_poll_interval_ms: float = 50.0
    wiegand_bit_timeout_ms: float = 5.0
    serial_queue_timeout_s: float = 1.0
    backend_sync_interval_s: float = 60.0
    auth_timeout_s: float = 30.0
    passage_timeout_s: float = 10.0
    thread_join_timeout_s: float = 5.0


@dataclass
class AccessConfig:
    """Access configuration."""
    static_key: str = ""
    dynamic_key: str = ""


@dataclass
class Config:
    """Main configuration."""
    mux: MuxConfig = field(default_factory=MuxConfig)
    shift: ShiftConfig = field(default_factory=ShiftConfig)
    wiegand: WiegandConfig = field(default_factory=WiegandConfig)
    serial: SerialConfig = field(default_factory=SerialConfig)
    config: Dict = field(default_factory=dict)  # General config section
    access: AccessConfig = field(default_factory=AccessConfig)
    timings: TimingsConfig = field(default_factory=TimingsConfig)


def load_config(config_path: str) -> Config:
    """Load configuration from YAML file."""
    import yaml
    from scud_lgtu.config import load
    
    raw_config = load(config_path)
    
    # Convert to typed config
    config = Config()
    
    # Mux
    if "mux" in raw_config:
        config.mux = MuxConfig(
            addr_pins=raw_config["mux"].get("addr_pins", {}),
            addr_labels=raw_config["mux"].get("addr_labels", []),
            input_pin=raw_config["mux"].get("input_pin", ""),
            poll_interval_ms=raw_config["mux"].get("poll_interval_ms", 50.0)
        )
    
    # Shift
    if "shift" in raw_config:
        config.shift = ShiftConfig(
            ser_data=raw_config["shift"].get("ser_data", ""),
            ser_clk=raw_config["shift"].get("ser_clk", ""),
            ser_latch=raw_config["shift"].get("ser_latch", ""),
            reg_len=raw_config["shift"].get("reg_len", 8)
        )
    
    # Wiegand
    if "wiegand" in raw_config:
        config.wiegand = WiegandConfig(
            readers=raw_config["wiegand"].get("readers", []),
            bit_timeout_ms=raw_config["wiegand"].get("bit_timeout_ms", 5.0)
        )
    
    # Serial
    if "serial" in raw_config:
        config.serial = SerialConfig(
            ports=raw_config["serial"].get("ports", []),
            queue_timeout_s=raw_config["serial"].get("queue_timeout_s", 1.0)
        )
    
    # Config (general)
    if "config" in raw_config:
        config.config = raw_config["config"]
    
    # Access
    if "access" in raw_config:
        config.access = AccessConfig(
            static_key=raw_config["access"].get("static_key", ""),
            dynamic_key=raw_config["access"].get("dynamic_key", "")
        )
    
    # Timings
    if "timings" in raw_config:
        config.timings = TimingsConfig(
            mux_poll_interval_ms=raw_config["timings"].get("mux_poll_interval_ms", 50.0),
            wiegand_bit_timeout_ms=raw_config["timings"].get("wiegand_bit_timeout_ms", 5.0),
            serial_queue_timeout_s=raw_config["timings"].get("serial_queue_timeout_s", 1.0),
            backend_sync_interval_s=raw_config["timings"].get("backend_sync_interval_s", 60.0),
            auth_timeout_s=raw_config["timings"].get("auth_timeout_s", 30.0),
            passage_timeout_s=raw_config["timings"].get("passage_timeout_s", 10.0),
            thread_join_timeout_s=raw_config["timings"].get("thread_join_timeout_s", 5.0)
        )
    
    return config
