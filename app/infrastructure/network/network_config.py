"""Загрузка и сохранение сетевого конфига контроллера.

Конфиг хранится рядом с config.yml в файле ``network_config.yml``
(либо по пути из переменной окружения ``LGTU_NETWORK_CONFIG``).
"""
from __future__ import annotations

import copy
import os
from typing import Any

import yaml


def _network_config_path(config_path: str | None = None) -> str:
    """Вернуть путь к network_config.yml."""
    env_path = os.environ.get("LGTU_NETWORK_CONFIG")
    if env_path:
        return os.path.abspath(env_path)
    if config_path:
        config_path = os.path.abspath(config_path)
    else:
        from app.infrastructure.config.config_loader import resolve_config_path
        config_path = resolve_config_path()
    return os.path.join(os.path.dirname(config_path), "network_config.yml")


def load(config_path: str | None = None) -> dict[str, Any]:
    """Загрузить сетевой конфиг."""
    path = _network_config_path(config_path)
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data if data is not None else {}


def save(config: dict[str, Any], config_path: str | None = None) -> None:
    """Сохранить сетевой конфиг."""
    path = _network_config_path(config_path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(copy.deepcopy(config), f, allow_unicode=True, sort_keys=False, indent=2)


def update(config_path: str | None, updates: dict[str, Any]) -> dict[str, Any]:
    """Обновить сетевой конфиг и вернуть объединённый результат."""
    cfg = load(config_path)
    cfg = _deep_update(cfg, updates)
    save(cfg, config_path)
    return cfg


def _deep_update(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Рекурсивно обновить base значениями из override."""
    result = copy.deepcopy(base)
    for key, value in override.items():
        if (
            key in result
            and isinstance(result[key], dict)
            and isinstance(value, dict)
        ):
            result[key] = _deep_update(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def defaults() -> dict[str, Any]:
    """Дефолтная структура сетевого конфига."""
    return {
        "network": {
            "hostname": "lgtu-controller",
            "timezone": "Europe/Moscow",
            "ntp_servers": ["0.ru.pool.ntp.org"],
            "ethernet": {
                "interface": "eth0",
                "method": "dhcp",
                "address": "",
                "netmask": "",
                "gateway": "",
                "dns": ["8.8.8.8", "8.8.4.4"],
            },
            "wifi": {
                "enabled": False,
                "interface": "wlan0",
                "ssid": "",
                "password": "",
                "method": "dhcp",
                "address": "",
                "netmask": "",
                "gateway": "",
                "dns": ["8.8.8.8", "8.8.4.4"],
            },
        }
    }
