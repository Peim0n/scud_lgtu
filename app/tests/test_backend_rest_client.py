"""Тесты низкоуровневого REST-клиента (п. 6.1-6.3 ТЗ) без реальной сети."""
import pytest

from app.infrastructure.backend.rest_client import RestClient, BackendApiError


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, text=""):
        self.status_code = status_code
        self._json_data = json_data
        self.text = text

    def json(self):
        if self._json_data is None:
            raise ValueError("no json")
        return self._json_data


class FakeSession:
    """Подменяет requests.Session — записывает вызовы, отдаёт заготовленный ответ."""

    def __init__(self, response: FakeResponse):
        self.response = response
        self.calls = []
        self.cert = None
        self.verify = None

    def post(self, url, data=None, headers=None, timeout=None):
        self.calls.append({"url": url, "data": data, "headers": headers, "timeout": timeout})
        return self.response


def _client_with_response(response: FakeResponse) -> tuple[RestClient, FakeSession]:
    session = FakeSession(response)
    client = RestClient("https://api.pass.lipetsk.ru", session=session)
    return client, session


def test_call_builds_correct_url_and_body():
    client, session = _client_with_response(FakeResponse(200, {"status": "ok"}))
    client.call("access", "get", {"update": 1})

    assert session.calls[0]["url"] == "https://api.pass.lipetsk.ru/controller/v1/access/get"
    assert session.calls[0]["data"] == b'{"update": 1}'
    assert session.calls[0]["headers"]["Content-Type"] == "application/json"


def test_call_with_no_payload_sends_null_body():
    client, session = _client_with_response(FakeResponse(200, {"status": "ok"}))
    client.call("accesspoint", "get")

    assert session.calls[0]["data"] == b"null"


def test_call_returns_json_on_200_ok():
    client, session = _client_with_response(FakeResponse(200, {"status": "ok", "quantity": 3}))
    result = client.call("keys", "get")
    assert result == {"status": "ok", "quantity": 3}


@pytest.mark.parametrize("status_code", [400, 403, 404, 405, 500])
def test_call_raises_on_error_http_status(status_code):
    client, _ = _client_with_response(FakeResponse(status_code, {"status": "error", "description": "boom"}))
    with pytest.raises(BackendApiError) as exc_info:
        client.call("event", "put", {"event_id": 1})
    assert exc_info.value.http_status == status_code


def test_call_raises_on_status_error_in_body_even_with_200():
    client, _ = _client_with_response(FakeResponse(200, {"status": "error", "description": "нет доступа"}))
    with pytest.raises(BackendApiError) as exc_info:
        client.call("access", "get")
    assert "нет доступа" in exc_info.value.description


def test_non_json_error_body_treated_as_error_status(monkeypatch):
    """п. 6.1: не-JSON тело трактуется как {"status":"error","description":"текст"}"""
    client, _ = _client_with_response(FakeResponse(500, json_data=None, text="internal error"))
    with pytest.raises(BackendApiError) as exc_info:
        client.call("event", "get")
    assert exc_info.value.description == "internal error"


def test_network_exception_raises_backend_api_error():
    class RaisingSession:
        cert = None
        verify = None

        def post(self, *args, **kwargs):
            raise ConnectionError("no route to host")

    client = RestClient("https://api.pass.lipetsk.ru", session=RaisingSession())
    with pytest.raises(BackendApiError):
        client.call("access", "get")


def test_set_client_cert_updates_session():
    client, session = _client_with_response(FakeResponse(200, {"status": "ok"}))
    client.set_client_cert("/tmp/cert.pem", "/tmp/key.pem")
    assert session.cert == ("/tmp/cert.pem", "/tmp/key.pem")
