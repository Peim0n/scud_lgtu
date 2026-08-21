"""
Общая загрузка настроек из app/config.yml для диагностических скриптов
(scripts/backend_check/*), чтобы они не расходились с реальным приложением
(в первую очередь — User-Agent, который должен совпадать с тем, что шлёт
CertificateManager/RestClient, иначе диагностика будет проверять не то,
с чем реально столкнётся контроллер на WAF).

Значения ниже можно переопределить переменными окружения (см. README) —
это удобно для разовых экспериментов, не трогая config.yml.
"""
from __future__ import annotations

import os

import yaml

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_CONFIG_PATH = os.path.join(_REPO_ROOT, "app", "config.yml")

# Фолбэк, если app/config.yml недоступен (например, скрипт запущен отдельно
# от репозитория) — держим в синхроне с DEFAULT_USER_AGENT из rest_client.py.
_FALLBACK_USER_AGENT = "LGTU-SCUD-Controller/1.0"


def _load_backend_config() -> dict:
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
    except OSError:
        return {}
    return config.get("backend", {}) or {}


_backend_config = _load_backend_config()

# User-Agent — по умолчанию берём из app/config.yml (backend.user_agent),
# чтобы диагностика проверяла то же самое, что реально шлёт приложение.
USER_AGENT = os.environ.get("USER_AGENT", _backend_config.get("user_agent", _FALLBACK_USER_AGENT))

# access_point_id — тоже удобно иметь один источник правды с config.yml.
DEFAULT_ACCESS_POINT_ID = str(_backend_config.get("access_point_id", "2"))
