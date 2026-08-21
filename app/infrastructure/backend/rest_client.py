"""
Низкоуровневый REST-клиент к бэкенду СКУД (п. 6 ТЗ).

Реализует общий протокол взаимодействия для ветви ``controller``:
- HTTPS + mTLS (клиентский сертификат/ключ);
- единственный метод HTTP — POST, тело — JSON (или пустое тело при
  отсутствии параметров);
- URL вида ``https://<host>/controller/v1/<resource>/<action>``;
- коды ошибок 200/400/403/404/405/500 (п. 6.3);
- TCP keepalive (п. 6.4).

Классы
------
- BackendApiError: ошибка ответа бэкенда (HTTP или бизнес-уровня)
- RestClient: REST-клиент ветви ``controller``
"""
from __future__ import annotations

import json
import logging
import socket
import ssl
from typing import Any, Optional

try:
    import requests
    from requests.adapters import HTTPAdapter
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

logger = logging.getLogger(__name__)

# Значения по умолчанию (п. 6.4 ТЗ). Переопределяются через конфиг.
_DEFAULT_TCP_KEEPALIVE_TIME_S = 300
_DEFAULT_TCP_KEEPALIVE_PROBES = 3
_DEFAULT_TCP_KEEPALIVE_INTVL_S = 20

_DEFAULT_API_PATH_PREFIX = "/controller/v1"

# WAF на бэкенде блокирует "ботовские" User-Agent (в т.ч. дефолтный
# python-requests/x.y) — используем свой чёткий UA, который бэкенд-команда
# должна внести в allowlist WAF (вместо маскировки под браузер).
DEFAULT_USER_AGENT = "LGTU-SCUD-Controller/1.0"


class BackendApiError(Exception):
    """Ошибка запроса к бэкенду (сетевая, HTTP-код или status=error в ответе)."""

    def __init__(self, message: str, http_status: Optional[int] = None, description: str = ""):
        super().__init__(message)
        self.http_status = http_status
        self.description = description


def _make_keepalive_adapter(
    keepalive_time: int,
    keepalive_intvl: int,
    keepalive_probes: int,
    ssl_context: Optional[Any] = None,
) -> type:
    """Фабрика HTTPAdapter с TCP keepalive (п. 6.4) и опционным SSL-контекстом."""
    if not REQUESTS_AVAILABLE:
        return object  # type: ignore[return-value]

    class _Adapter(HTTPAdapter):
        def init_poolmanager(self, *args, **kwargs):
            socket_options = [
                (socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1),
            ]
            if hasattr(socket, "TCP_KEEPIDLE"):
                socket_options.append((socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, keepalive_time))
            if hasattr(socket, "TCP_KEEPINTVL"):
                socket_options.append((socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, keepalive_intvl))
            if hasattr(socket, "TCP_KEEPCNT"):
                socket_options.append((socket.IPPROTO_TCP, socket.TCP_KEEPCNT, keepalive_probes))
            kwargs["socket_options"] = socket_options
            if ssl_context is not None:
                kwargs["ssl_context"] = ssl_context
            return super().init_poolmanager(*args, **kwargs)

    return _Adapter


class RestClient:
    """
    REST-клиент к ветви ``controller`` бэкенда СКУД.

    Parameters
    ----------
    base_url : str
        Базовый адрес бэкенда, например ``https://api.pass.lipetsk.ru``.
    client_cert : tuple[str, str] | None
        Путь к (сертификат, приватный ключ) клиента в PEM для mTLS.
        Может быть None до получения рабочего сертификата (тогда доступен
        только ресурс ``cert`` с первичным сертификатом, переданным явно).
    ca_bundle : str | None
        Путь к CA-сертификату для проверки сервера. Если None — используется
        системное хранилище доверенных сертификатов.
    timeout : float
        Таймаут запроса в секундах.
    session : Any, optional
        Готовая ``requests.Session`` (или совместимый объект) — используется
        в тестах для подмены транспорта без реальной сети.
    """

    def __init__(
        self,
        base_url: str,
        client_cert: Optional[tuple[str, str]] = None,
        ca_bundle: Optional[str] = None,
        timeout: float = 10.0,
        session: Optional[Any] = None,
        api_path_prefix: str = _DEFAULT_API_PATH_PREFIX,
        tcp_keepalive_time: int = _DEFAULT_TCP_KEEPALIVE_TIME_S,
        tcp_keepalive_probes: int = _DEFAULT_TCP_KEEPALIVE_PROBES,
        tcp_keepalive_intvl: int = _DEFAULT_TCP_KEEPALIVE_INTVL_S,
        endpoint_map: Optional[dict[str, str]] = None,
        method_map: Optional[dict[str, str]] = None,
        verify_hostname: bool = True,
        user_agent: str = DEFAULT_USER_AGENT,
    ) -> None:
        if not REQUESTS_AVAILABLE and session is None:
            raise ImportError("Модуль requests не установлен. Установите: pip install requests")

        self._base_url = base_url.rstrip("/")
        self._api_path_prefix = api_path_prefix.strip("/")
        self._timeout = timeout
        self._client_cert = client_cert
        self._ca_bundle = ca_bundle
        self._endpoint_map = endpoint_map or {}
        self._method_map = method_map or {}
        self._verify_hostname = verify_hostname
        self._user_agent = user_agent
        self._tcp_keepalive_time = tcp_keepalive_time
        self._tcp_keepalive_intvl = tcp_keepalive_intvl
        self._tcp_keepalive_probes = tcp_keepalive_probes

        if session is not None:
            self._session = session
        else:
            ssl_context = None
            if not verify_hostname:
                ssl_context = ssl.create_default_context()
                ssl_context.check_hostname = False
                if ca_bundle is not None:
                    ssl_context.load_verify_locations(ca_bundle)

            adapter_cls = _make_keepalive_adapter(
                tcp_keepalive_time, tcp_keepalive_intvl, tcp_keepalive_probes,
                ssl_context=ssl_context,
            )
            self._session = requests.Session()
            self._session.mount("https://", adapter_cls())
            if client_cert is not None:
                self._session.cert = client_cert
            if ca_bundle is not None:
                # Если SSL-контекст создан вручную, verify=True чтобы urllib3 его использовал.
                self._session.verify = True if ssl_context is not None else ca_bundle
            elif not verify_hostname:
                # verify=False отключит проверку CA; для отладки можно, но небезопасно.
                self._session.verify = True

    def set_client_cert(self, cert_path: str, key_path: str) -> None:
        """Обновить клиентский сертификат/ключ (после первичной выдачи или ротации)."""
        self._client_cert = (cert_path, key_path)
        self._session.cert = (cert_path, key_path)

    def set_ca_bundle(self, ca_bundle: Optional[str]) -> None:
        """Обновить CA-сертификат для проверки сервера (например, полученный от KMS)."""
        self._ca_bundle = ca_bundle
        if ca_bundle is None:
            return

        if self._verify_hostname:
            self._session.verify = ca_bundle
            return

        # Если проверка hostname отключена (например, коннект по IP), нужно
        # пересоздать SSL-контекст с check_hostname=False и новым CA.
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.load_verify_locations(ca_bundle)
        adapter_cls = _make_keepalive_adapter(
            self._tcp_keepalive_time,
            self._tcp_keepalive_intvl,
            self._tcp_keepalive_probes,
            ssl_context=ssl_context,
        )
        self._session.mount("https://", adapter_cls())
        self._session.verify = True

    def call(self, resource: str, action: str, payload: Optional[dict] = None) -> dict[str, Any]:
        """
        Выполнить HTTP-запрос к backend.

        URL формируется как ``<api_path_prefix>/<resource>/<action>``,
        но может быть переопределён через ``endpoint_map`` (например,
        ``{"cert/get": "/controller/v1/cert"}``). Метод по умолчанию — POST,
        но для конкретного ``resource/action`` можно задать другой через
        ``method_map`` (например, ``{"keys/get": "GET"}``).

        Parameters
        ----------
        resource : str
            Имя ресурса (``keys``, ``cert``, ``access``, ``accesspoint``, ``event``).
        action : str
            Действие (``get``, ``put``, ``patch``).
        payload : dict, optional
            Тело запроса. None — запрос с пустым (null) телом.

        Returns
        -------
        dict
            Разобранный JSON-ответ (гарантированно содержит поле ``status``).

        Raises
        ------
        BackendApiError
            При сетевой ошибке, неожиданном HTTP-коде или ``status=error``.
        """
        key = f"{resource}/{action}" if action else resource
        default_path = f"/{self._api_path_prefix}/{resource}"
        if action:
            default_path += f"/{action}"
        path = self._endpoint_map.get(key, default_path)
        url = f"{self._base_url}{path}" if path.startswith("/") else f"{self._base_url}/{path}"
        method = self._method_map.get(key, "POST")

        headers = {"Accept": "application/json", "User-Agent": self._user_agent}
        try:
            if method.upper() == "GET":
                # GET не имеет тела — параметры (если есть) передаются в query string.
                response = self._session.get(url, params=payload, headers=headers, timeout=self._timeout)
            elif method.upper() == "POST":
                body = json.dumps(payload, ensure_ascii=False) if payload is not None else "null"
                headers["Content-Type"] = "application/json"
                response = self._session.post(
                    url,
                    data=body.encode("utf-8"),
                    headers=headers,
                    timeout=self._timeout,
                )
            else:
                body = json.dumps(payload, ensure_ascii=False) if payload is not None else "null"
                headers["Content-Type"] = "application/json"
                response = self._session.request(
                    method,
                    url,
                    data=body.encode("utf-8"),
                    headers=headers,
                    timeout=self._timeout,
                )
        except Exception as exc:
            raise BackendApiError(f"Сетевая ошибка при вызове {resource}/{action}: {exc}") from exc

        return self._parse_response(response, resource, action)

    def _parse_response(self, response: Any, resource: str, action: str) -> dict[str, Any]:
        """Разобрать HTTP-ответ по правилам п. 6.1/6.3 ТЗ."""
        status_code = response.status_code

        try:
            data = response.json()
        except Exception:
            # Не-JSON тело трактуется как '{"status":"error","description":"<текст>"}' (п. 6.1).
            data = {"status": "error", "description": getattr(response, "text", "")}

        if status_code != 200:
            description = data.get("description", "") if isinstance(data, dict) else ""
            raise BackendApiError(
                f"{resource}/{action}: HTTP {status_code}",
                http_status=status_code,
                description=description,
            )

        if isinstance(data, dict) and data.get("status") == "error":
            raise BackendApiError(
                f"{resource}/{action}: status=error",
                http_status=status_code,
                description=data.get("description", ""),
            )

        return data
