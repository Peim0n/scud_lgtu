"""Хранение учётных данных веб-интерфейса.

Учётки хранятся в файле ``web_auth.yml`` рядом с config.yml.
Формат::

    username: admin
    password_hash: <pbkdf2 hex>
    password_salt: <salt hex>

Пароли хранятся как PBKDF2-HMAC-SHA256 hash с salt (не plaintext).
При первом запуске, если файла нет, используется дефолт admin/admin.
"""
from __future__ import annotations

import hashlib
import os
import secrets
from typing import Any

import yaml

# PBKDF2 параметры: 100000 итераций, SHA-256, 32 байта salt
_PBKDF2_ITERATIONS = 100_000
_PBKDF2_KEY_LEN = 32
_SALT_LEN = 32


def _auth_config_path(config_path: str | None = None) -> str:
    """Вернуть путь к web_auth.yml: /etc/scud_lgtu/ или рядом с config.yml."""
    runtime_dir = "/etc/scud_lgtu"
    if os.path.isdir(runtime_dir):
        return os.path.join(runtime_dir, "web_auth.yml")
    if config_path is None:
        from app.infrastructure.config.config_loader import resolve_config_path
        config_path = resolve_config_path()
    config_path = os.path.abspath(config_path)
    return os.path.join(os.path.dirname(config_path), "web_auth.yml")


def _hash_password(password: str, salt: bytes | None = None) -> tuple[str, str]:
    """Вернуть (pbkdf2_hex, salt_hex) для пароля.

    Если salt не передан — генерируется новый случайный.
    """
    if salt is None:
        salt = secrets.token_bytes(_SALT_LEN)
    dk = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS, _PBKDF2_KEY_LEN
    )
    return dk.hex(), salt.hex()


def load(config_path: str | None = None) -> dict[str, str]:
    """Загрузить учётные данные. Если файла нет — вернуть дефолт admin/admin."""
    path = _auth_config_path(config_path)
    if not os.path.exists(path):
        # Дефолт admin/admin с фиксированным salt (чтобы hash был детерминирован
        # для дефолтных данных — при первом запуске пользователь должен сменить).
        default_hash, default_salt = _hash_password("admin", b"\x00" * _SALT_LEN)
        return {
            "username": "admin",
            "password_hash": default_hash,
            "password_salt": default_salt,
        }
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not data:
        default_hash, default_salt = _hash_password("admin", b"\x00" * _SALT_LEN)
        return {
            "username": "admin",
            "password_hash": default_hash,
            "password_salt": default_salt,
        }
    return {
        "username": data.get("username", "admin"),
        "password_hash": data.get("password_hash", ""),
        "password_salt": data.get("password_salt", ""),
    }


def save(username: str, password: str, config_path: str | None = None) -> None:
    """Сохранить учётные данные (пароль хешируется с новым salt)."""
    path = _auth_config_path(config_path)
    password_hash, salt_hex = _hash_password(password)
    data = {
        "username": username,
        "password_hash": password_hash,
        "password_salt": salt_hex,
    }
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False, indent=2)


def check(username: str, password: str, config_path: str | None = None) -> bool:
    """Проверить логин/пароль."""
    creds = load(config_path)
    if username != creds["username"]:
        return False
    if not creds["password_hash"] or not creds["password_salt"]:
        return False
    # Вычисляем hash с тем же salt
    computed_hash, _ = _hash_password(password, bytes.fromhex(creds["password_salt"]))
    # Constant-time comparison
    return secrets.compare_digest(computed_hash, creds["password_hash"])
