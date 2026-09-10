"""
Клиент для взаимодействия с бэкендом системы СКУД (ветвь ``controller``, п. 6.5 ТЗ).

Реализует ресурсы: ``keys`` (ключи QR/карт), ``access`` (список доступа),
``accesspoint`` (инвентаризация контроллера), ``event`` (выгрузка событий).
Ресурс ``cert`` используется напрямую ``CertificateManager`` через тот же
``RestClient``.

Классы
------
- BackendClient: REST API клиент ветви ``controller``
"""

import logging
from typing import Any

from app.infrastructure.backend.rest_client import BackendApiError, RestClient
from app.infrastructure.persistence.event_store import PassageEvent

logger = logging.getLogger(__name__)


class BackendClient:
    """Клиент REST API бэкенда для контроллера турникета."""

    def __init__(
        self,
        base_url: str | None = None,
        rest_client: RestClient | None = None,
        **rest_client_kwargs,
    ) -> None:
        """
        Parameters
        ----------
        base_url : str, optional
            Базовый URL бэкенда. Используется только если ``rest_client`` не передан.
        rest_client : RestClient, optional
            Готовый REST-клиент (для тестов/переиспользования между сервисами).
        **rest_client_kwargs
            Дополнительные параметры для ``RestClient`` (client_cert, ca_bundle, timeout, session).
        """
        if rest_client is not None:
            self._rest = rest_client
        else:
            if base_url is None:
                raise ValueError("Нужно указать base_url или rest_client")
            self._rest = RestClient(base_url, **rest_client_kwargs)
        self._online = False

    @property
    def rest_client(self) -> RestClient:
        return self._rest

    def is_online(self) -> bool:
        """Вернуть кэшированный статус связи (обновляется при каждом вызове API)."""
        return self._online

    def mark_online(self) -> None:
        """
        Явно отметить соединение как установленное.

        Нужен, когда факт успешного mTLS-соединения известен из вызова,
        сделанного мимо ``BackendClient`` напрямую через тот же
        ``RestClient`` — например, первичный обмен/ротация сертификата в
        ``CertificateManager`` (см. bootstrap.py). Без этого ``is_online()``
        оставался бы ложно ``False`` до первого собственного вызова
        ``BackendClient``, хотя соединение уже подтверждено.
        """
        self._online = True

    def mark_offline(self) -> None:
        """Явно отметить соединение как разорванное (например, при неудачной ротации сертификата)."""
        self._online = False

    def check_connectivity(self) -> bool:
        """Активно проверить связь лёгким запросом (``accesspoint/get``)."""
        try:
            self.get_accesspoint()
            return True
        except BackendApiError:
            return False

    # ------------------------------------------------------------------
    # Ресурс keys (п. 5.4.2)
    # ------------------------------------------------------------------

    def get_keys(self) -> list[dict[str, Any]]:
        """Получить список наборов ключей QR/карт «МИР» (до 31 набора)."""
        response = self._call("keys", "get")
        return response.get("keys", [])

    # ------------------------------------------------------------------
    # Ресурс access (п. 5.4.3)
    # ------------------------------------------------------------------

    def get_access_list(self, update: int = 1) -> dict[str, Any]:
        """
        Получить список идентификаторов доступа.

        Parameters
        ----------
        update : int
            0 — запросить полный список принудительно; 1 (по умолчанию) —
            вернуть список только если были изменения с прошлого запроса.
        """
        return self._call("access", "get", {"update": update})

    # ------------------------------------------------------------------
    # Ресурс accesspoint (инвентаризация)
    # ------------------------------------------------------------------

    def get_accesspoint(self) -> dict[str, Any]:
        """Запросить зарегистрированные данные точки доступа (mac/ip/cpuid)."""
        return self._call("accesspoint", "get")

    def patch_accesspoint(self, mac: str, ip: str, cpuid: str) -> dict[str, Any]:
        """Отправить инвентаризационные данные контроллера."""
        return self._call(
            "accesspoint", "patch", {"mac": mac, "ip": ip, "cpuid": cpuid}
        )

    # ------------------------------------------------------------------
    # Ресурс event (п. 6.5, идемпотентность передачи, п. 3)
    # ------------------------------------------------------------------

    def get_last_event(self) -> dict[str, Any]:
        """Получить event_id/stime/ftime последнего принятого бэкендом события."""
        return self._call("event", "get")

    def put_event(self, event: PassageEvent) -> dict[str, Any]:
        """Отправить одно событие на бэкенд (§6.5, таблица log из §5.5)."""
        payload = {
            "event_id": event.event_id,
            "stime": _iso(event.stime),
            "event_type": event.event_type,
            "severity": event.severity,
            # description — обязательное поле в event/put по ТЗ (§6.5)
            "description": event.description or "",
        }
        optional_fields = {
            "direction": event.direction,
            "token_type": event.token_type,
            "token": event.token,
            "result": event.result,
        }
        payload.update(
            {key: value for key, value in optional_fields.items() if value is not None}
        )
        if event.ftime is not None:
            payload["ftime"] = _iso(event.ftime)
        return self._call("event", "put", payload)

    def send_events(self, events: list[PassageEvent]) -> bool:
        """
        Отправить накопленные события по одному (ресурс ``event`` принимает
        только одно событие за запрос put). Останавливается на первой ошибке,
        чтобы не терять порядок и не потерять недошедшие события молча.
        """
        if not events:
            return True
        for event in events:
            try:
                self.put_event(event)
            except BackendApiError as exc:
                logger.warning(
                    "BackendClient.send_events: не удалось отправить событие %s: %s",
                    event.event_id,
                    exc,
                )
                return False
        return True

    # ------------------------------------------------------------------
    # Внутреннее
    # ------------------------------------------------------------------

    def _call(
        self, resource: str, action: str, payload: dict | None = None
    ) -> dict[str, Any]:
        try:
            result = self._rest.call(resource, action, payload)
        except BackendApiError:
            self._online = False
            raise
        self._online = True
        return result


def _iso(timestamp: float) -> str:
    """Преобразовать unix timestamp в ISO 8601 строку с временной зоной."""
    import datetime

    return datetime.datetime.fromtimestamp(timestamp).astimezone().isoformat()
