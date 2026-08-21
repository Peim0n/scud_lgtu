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
    "backend": "Бэкенд (сервер доступа)",
    "backend.base_url": "Адрес сервера бэкенда (URL)",
    "backend.api_path_prefix": "Префикс API-путей",
    "backend.kms_url": "Адрес KMS-сервера для выдачи сертификатов",
    "backend.access_point_id": "ID точки доступа на сервере",
    "backend.verify_hostname": "Проверять имя хоста в сертификате сервера",
    "backend.user_agent": "User-Agent для HTTP-запросов",
    "backend.request_timeout_s": "Таймаут запроса к серверу (сек)",
    "backend.tcp_keepalive_time_s": "TCP keepalive: интервал (сек)",
    "backend.tcp_keepalive_probes": "TCP keepalive: количество проб",
    "backend.tcp_keepalive_intvl_s": "TCP keepalive: интервал между пробами (сек)",

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
    "backend.base_url": (
        "Адрес сервера СКУД, к которому контроллер обращается для "
        "проверки доступа, событий и ротации сертификатов."
    ),
    "backend.api_path_prefix": (
        "Префикс пути в URL API. По умолчанию «controller/v1». "
        "Не меняйте без согласования с бэкенд-командой."
    ),
    "backend.kms_url": (
        "Адрес сервера ключей (KMS), который выдаёт первичный сертификат "
        "при первом запуске контроллера. После успешного обмена первичный "
        "сертификат удаляется."
    ),
    "backend.access_point_id": (
        "Идентификатор точки доступа, к которой привязан этот контроллер. "
        "Используется в каждом запросе к серверу."
    ),
    "backend.verify_hostname": (
        "Отключите, если подключаетесь к серверу по IP-адресу, "
        "а имя хоста в сертификате не совпадает."
    ),
    "backend.user_agent": (
        "Используется для allowlist на WAF бэкенда. "
        "Не меняйте без согласования с бэкенд-командой."
    ),
    "backend.request_timeout_s": (
        "Сколько секунд ждать ответа от сервера перед ошибкой."
    ),
    "backend.tcp_keepalive_time_s": (
        "Время простоя TCP-соединения до отправки первого keepalive-пакета."
    ),
    "backend.tcp_keepalive_probes": (
        "Количество неподтверждённых keepalive-проб до разрыва соединения."
    ),
    "backend.tcp_keepalive_intvl_s": (
        "Интервал между keepalive-пробами при отсутствии ответа."
    ),
    "qr_decoder.base_url": (
        "URL QR-сервиса, к которому обращается внешняя камера для "
        "декодирования QR-кодов посетителей."
    ),
    "web.host": (
        "IP-адрес, на котором веб-интерфейс принимает подключения. "
        "0.0.0.0 — все интерфейсы."
    ),
    "web.port": (
        "TCP-порт веб-интерфейса. По умолчанию 8080."
    ),
}

# Поля, которые скрыты из веб-интерфейса (инфраструктурные)
HIDDEN_FIELDS: set[str] = {
    "backend.ca_bundle",
    "backend.network_interface",
}


def get_label(path: str) -> str:
    """Вернуть человекочитаемую подпись для dotted-пути."""
    return LABELS.get(path, path)


def get_description(path: str) -> str | None:
    """Вернуть описание поля или None."""
    return DESCRIPTIONS.get(path)


def is_hidden(path: str) -> bool:
    """Скрыто ли поле из веб-интерфейса."""
    return path in HIDDEN_FIELDS
