"""Тесты BackendClient — ресурсы ветви controller (п. 6.5 ТЗ) без реальной сети."""
import pytest

from app.infrastructure.backend.client import BackendClient
from app.infrastructure.backend.rest_client import RestClient, BackendApiError
from app.infrastructure.persistence.event_store import PassageEvent


class FakeResponse:
    def __init__(self, status_code=200, json_data=None):
        self.status_code = status_code
        self._json_data = json_data if json_data is not None else {"status": "ok"}
        self.text = ""

    def json(self):
        return self._json_data


class FakeSession:
    def __init__(self, responses=None, default_response=None):
        self._responses = responses or []
        self._default = default_response or FakeResponse()
        self.calls = []
        self.cert = None
        self.verify = None

    def post(self, url, data=None, headers=None, timeout=None):
        self.calls.append({"url": url, "data": data})
        if self._responses:
            return self._responses.pop(0)
        return self._default


def _backend_with_session(session: FakeSession) -> BackendClient:
    rest = RestClient("https://api.pass.lipetsk.ru", session=session)
    return BackendClient(rest_client=rest)


def test_get_keys_returns_key_list():
    session = FakeSession(default_response=FakeResponse(200, {
        "status": "ok", "quantity": 1,
        "keys": [{"num": 1, "public": "aa" * 32, "shared": "bb" * 16, "dynamic": "cc" * 32}],
    }))
    backend = _backend_with_session(session)

    keys = backend.get_keys()

    assert len(keys) == 1
    assert keys[0]["num"] == 1
    assert backend.is_online() is True


def test_get_access_list_passes_update_flag():
    session = FakeSession(default_response=FakeResponse(200, {"status": "ok", "update": 0, "id": []}))
    backend = _backend_with_session(session)

    backend.get_access_list(update=0)

    assert b'"update": 0' in session.calls[0]["data"]


def test_patch_accesspoint_sends_inventory_fields():
    session = FakeSession(default_response=FakeResponse(200, {"status": "ok"}))
    backend = _backend_with_session(session)

    backend.patch_accesspoint(mac="aa:bb:cc:dd:ee:ff", ip="10.0.0.5", cpuid="deadbeef")

    body = session.calls[0]["data"].decode("utf-8")
    assert "aa:bb:cc:dd:ee:ff" in body
    assert "10.0.0.5" in body
    assert "deadbeef" in body


def test_put_event_sends_required_fields():
    session = FakeSession(default_response=FakeResponse(200, {"status": "ok"}))
    backend = _backend_with_session(session)
    event = PassageEvent(
        event_id=42, stime=1_700_000_000.0, event_type="access", direction="in",
        token_type="maxid", token="1234567", result="pass", severity="info",
    )

    backend.put_event(event)

    body = session.calls[0]["data"].decode("utf-8")
    assert '"event_id": 42' in body
    assert '"token": "1234567"' in body


def test_send_events_stops_on_first_failure_and_returns_false():
    session = FakeSession(responses=[
        FakeResponse(200, {"status": "ok"}),
        FakeResponse(500, {"status": "error", "description": "db down"}),
    ])
    backend = _backend_with_session(session)
    events = [
        PassageEvent(event_id=1, event_type="access", token_type="maxid", token="1", result="pass"),
        PassageEvent(event_id=2, event_type="access", token_type="maxid", token="2", result="pass"),
        PassageEvent(event_id=3, event_type="access", token_type="maxid", token="3", result="pass"),
    ]

    result = backend.send_events(events)

    assert result is False
    assert len(session.calls) == 2  # третье событие не отправлялось после ошибки
    assert backend.is_online() is False


def test_send_events_empty_list_returns_true_without_calls():
    session = FakeSession()
    backend = _backend_with_session(session)

    assert backend.send_events([]) is True
    assert session.calls == []


def test_is_online_false_until_first_successful_call():
    session = FakeSession(default_response=FakeResponse(200, {"status": "ok"}))
    backend = _backend_with_session(session)

    assert backend.is_online() is False
    backend.get_accesspoint()
    assert backend.is_online() is True


def test_check_connectivity_false_on_backend_error():
    session = FakeSession(default_response=FakeResponse(500, {"status": "error"}))
    backend = _backend_with_session(session)

    assert backend.check_connectivity() is False
