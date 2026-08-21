"""Хранение учётных данных веб-интерфейса.

Учётки хранятся в файле ``web_auth.yml`` рядом с config.yml.
Формат::

    username: admin
    password_hash: <sha256 hex>

Пароли хранятся как SHA-256 hash (не plaintext). При первом запуске,
если файла нет, используется дефолт admin/admin.
"""
from __future__ import annotations

import hashlib
import os
from typing import Any

import yaml


def _auth_config_path(config_path: str | None = None) -> str:
    """Вернуть путь к web_auth.yml."""
    if config_path is None:
        from app.infrastructure.config.config_loader import resolve_config_path
        config_path = resolve_config_path()
    config_path = os.path.abspath(config_path)
    return os.path.join(os.path.dirname(config_path), "web_auth.yml")


def _hash_password(password: str) -> str:
    """Вернуть SHA-256 hash пароля."""
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def load(config_path: str | None = None) -> dict[str, str]:
    """Загрузить учётные данные. Если файла нет — вернуть дефолт admin/admin."""
    path = _auth_config_path(config_path)
    if not os.path.exists(path):
        return {"username": "admin", "password_hash": _hash_password("admin")}
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not data:
        return {"username": "admin", "password_hash": _hash_password("admin")}
    return {
        "username": data.get("username", "admin"),
        "password_hash": data.get("password_hash", _hash_password("admin")),
    }


def save(username: str, password: str, config_path: str | None = None) -> None:
    """Сохранить учётные данные (пароль хешируется)."""
    path = _auth_config_path(config_path)
    data = {
        "username": username,
        "password_hash": _hash_password(password),
    }
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False, indent=2)


def check(username: str, password: str, config_path: str | None = None) -> bool:
    """Проверить логин/пароль."""
    creds = load(config_path)
    return (
        username == creds["username"]
        and _hash_password(password) == creds["password_hash"]
    )
