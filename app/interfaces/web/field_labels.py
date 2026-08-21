"""Человекочитаемые подписи для полей конфигурации в веб-интерфейсе.

Связывает dotted-пути конфига с понятными русскими названиями.
Используется шаблонами backend.html и cert.html.
"""
from __future__ import annotations

LABELS: dict[str, str] = {
    # ── device ──
    "device": "Устройство",
    "device.type": "Тип управляемого устройства",

    # ── access ──
    "access": "Доступ",
    "access.static_key": "Статический ключ точки доступа (hex, 16 байт)",

    # ── qr_decoder ──
    "qr_decoder": "QR-декодер",
    "qr_decoder.base_url": "Базовый URL QR-сервиса",

    # ── backend ──
    "backend": "Бэкенд",
    "backend.base_url": "Адрес контроллера (URL)",
    "backend.api_path_prefix": "Префикс API-путей",
    "backend.kms_url": "Адрес KMS-сервера",
    "backend.ca_bundle": "CA-сертификат для проверки сервера (путь или null)",
    "backend.access_point_id": "ID точки доступа",
    "backend.verify_hostname": "Проверять hostname в сертификате сервера",
    "backend.user_agent": "User-Agent для HTTP-запросов",
    "backend.request_timeout_s": "Таймаут запроса (сек)",
    "backend.tcp_keepalive_time_s": "TCP keepalive: интервал (сек)",
    "backend.tcp_keepalive_probes": "TCP keepalive: количество проб",
    "backend.tcp_keepalive_intvl_s": "TCP keepalive: интервал между пробами (сек)",
    "backend.network_interface": "Сетевой интерфейс для инвентаризации (или null)",

    # ── web ──
    "web": "Веб-интерфейс",
    "web.enabled": "Включён",
    "web.port": "Порт",
    "web.host": "Адрес привязки",
}

# Описания для полей, где подписи недостаточно
DESCRIPTIONS: dict[str, str] = {
    "access.static_key": (
        "Уникален для точки доступа. Должен совпадать с ключом, "
        "прописанным в Wiegand-считывателях (ЭРА) через USB-конфигуратор."
    ),
    "backend.verify_hostname": (
        "Отключите, если подключаетесь к контроллеру по IP-адресу, "
        "а имя хоста в сертификате не совпадает."
    ),
    "backend.user_agent": (
        "Используется для allowlist на WAF бэкенда. "
        "Не меняйте без согласования с бэкенд-командой."
    ),
    "backend.network_interface": (
        "Имя интерфейса для отправки MAC-адреса в accesspoint/patch. "
        "null — автоопределение."
    ),
}


def get_label(path: str) -> str:
    """Вернуть человекочитаемую подпись для dotted-пути."""
    return LABELS.get(path, path)


def get_description(path: str) -> str | None:
    """Вернуть описание поля или None."""
    return DESCRIPTIONS.get(path)
