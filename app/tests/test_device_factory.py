"""Тесты фабрики управляемых устройств."""
from unittest.mock import MagicMock

import pytest

from app.infrastructure.devices.device_factory import create_device
from app.infrastructure.devices.turnstile.turnstile_device import TurnstileDevice


def _resolver():
    resolver = MagicMock()
    resolver.get_timing.return_value = 5.0
    return resolver


def test_factory_defaults_to_turnstile():
    device = create_device({}, timings={}, resolver=_resolver())
    assert isinstance(device, TurnstileDevice)


def test_factory_turnstile_by_type():
    device = create_device({"device": {"type": "turnstile"}}, timings={}, resolver=_resolver())
    assert isinstance(device, TurnstileDevice)


def test_factory_unknown_type_raises():
    with pytest.raises(ValueError):
        create_device({"device": {"type": "unknown"}}, timings={}, resolver=_resolver())
