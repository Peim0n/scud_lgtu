"""Фабрика управляемых устройств (турникет, ворота и т.п.).

Выбирает реализацию доменного устройства по полю ``device.type``
в объединённом конфиге. Параметры устройства берутся из соответствующей
секции конфига (например, ``turnstile``) через ModuleResolver.
"""
from __future__ import annotations

import logging
from typing import Any

from app.domain.access_device import AccessDevice
from app.infrastructure.devices.turnstile.turnstile_device import TurnstileDevice

logger = logging.getLogger(__name__)

# Реестр поддерживаемых типов устройств.
# Ключ — значение device.type, значение — фабричная функция.
# Новые устройства добавляются сюда после реализации модуля.
_REGISTRY: dict[str, Any] = {}


def _register(name: str, factory: Any) -> None:
    _REGISTRY[name] = factory


def _make_turnstile(auth_timeout: float, timings: dict, resolver: Any) -> AccessDevice:
    return TurnstileDevice(auth_timeout=auth_timeout, timings=timings, resolver=resolver)


_register("turnstile", _make_turnstile)


def available_device_types() -> list[str]:
    """Вернуть список поддерживаемых типов устройств."""
    return sorted(_REGISTRY.keys())


def create_device(config: dict[str, Any], timings: dict, resolver: Any) -> AccessDevice:
    """Создать экземпляр устройства доступа по конфигурации.

    Parameters
    ----------
    config : dict
        Объединённый конфиг (config.yml + object_config.yml).
    timings : dict
        Секция timings.
    resolver : ModuleResolver
        Резолвер конфига.

    Returns
    -------
    AccessDevice

    Raises
    ------
    ValueError
        Если тип устройства не поддерживается.
    """
    device_type = config.get("device", {}).get("type", "turnstile")
    auth_timeout = resolver.get_timing("business", "auth_timeout_s")

    factory = _REGISTRY.get(device_type)
    if factory is None:
        raise ValueError(
            f"Неизвестный тип устройства: {device_type}. "
            f"Доступные: {', '.join(available_device_types())}"
        )

    return factory(auth_timeout=auth_timeout, timings=timings, resolver=resolver)
