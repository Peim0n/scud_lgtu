"""
Интеграционные тесты взаимодействия с backend (§5.4, §6 ТЗ) — БЕЗ подмены
``requests.Session``. Поднимается настоящий локальный HTTPS+mTLS сервер
(``integration_backend_server.FakeBackendServer``) на 127.0.0.1, и клиент
контроллера (RestClient/BackendClient/CertificateManager/build_application)
обращается к нему через реальный TLS-хендшейк и реальный HTTP.

Конфигурация не хардкодится в тестах: тестовый ``config.yml`` собирается на
основе реального ``app/config.yml`` (то есть той же схемы, что и в
production), с точечной подменой только адреса backend/CA/путей к
сертификатам на тестовые значения.
"""
import os
import time

import pytest
import yaml

from app.tests.integration_backend_server import FakeBackendServer, issue_certificate

from app.infrastructure.backend.rest_client import RestClient, BackendApiError
from app.infrastructure.backend.client import BackendClient
from app.infrastructure.backend.certificate_manager import CertificateManager, CertificateSubject
from app.infrastructure.persistence.event_store import PassageEvent


@pytest.fixture(autouse=True)
def _no_proxy_for_localhost(monkeypatch):
    """
    Отключить системные HTTP(S)_PROXY для этих тестов: сервер поднимается на
    127.0.0.1, и если в окружении настроен прокси (например, в CI/песочнице),
    requests пытается тунелировать через него запросы к localhost и падает
    с ProxyError, не имеющим отношения к тестируемой логике.
    """
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")


@pytest.fixture
def server():
    srv = FakeBackendServer()
    srv.start()
    yield srv
    srv.stop()


def _write(path: str, content: str) -> str:
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


@pytest.fixture
def ca_bundle_path(server, tmp_path):
    return _write(str(tmp_path / "ca.pem"), server.ca_cert_pem)


# ---------------------------------------------------------------------------
# 1. Первичный обмен сертификата и ротация — против настоящего TLS-сервера
# ---------------------------------------------------------------------------

def test_certificate_bootstrap_over_real_mtls(server, ca_bundle_path, tmp_path):
    initial_cert_pem, initial_key_pem = server.issue_initial_client_certificate("turnstile-01")
    initial_cert_path = _write(str(tmp_path / "initial_cert.pem"), initial_cert_pem)
    initial_key_path = _write(str(tmp_path / "initial_key.pem"), initial_key_pem)

    rest = RestClient(server.base_url, ca_bundle=ca_bundle_path, timeout=5.0)
    subject = CertificateSubject(organization="Школа №1", organizational_units=["Корпус 1"], common_name="turnstile-01")
    manager = CertificateManager(
        rest, cert_dir=str(tmp_path / "certs"), subject=subject,
        initial_cert_path=initial_cert_path, initial_key_path=initial_key_path,
    )

    backend = BackendClient(rest_client=rest)
    manager._on_exchange_success = backend.mark_online

    manager.ensure_bootstrapped()

    assert manager.has_working_certificate
    assert not os.path.exists(initial_cert_path)  # первичный сертификат удалён
    assert len(server.cert_requests) == 1
    # is_online() должен стать True сразу после bootstrap, даже без
    # собственного вызова BackendClient (см. on_exchange_success/mark_online).
    assert backend.is_online() is True

    # Рабочим сертификатом должны проходить дальнейшие реальные mTLS-запросы.
    keys = backend.get_keys()
    assert keys == []


def test_certificate_rotation_over_real_mtls(server, ca_bundle_path, tmp_path):
    """
    Сервер выдаёт notBefore/notAfter по реальным часам (datetime.now()), а не
    по искусственно переведённым — поэтому вместо "перемотки времени" делаем
    рабочий сертификат коротким (notBefore на сутки в прошлом, см. sign_csr,
    notAfter = "сейчас" + 1 сутки), тогда сразу после выдачи остаётся ровно
    половина срока действия — гарантированно за порогом ротации (по
    умолчанию 0.5), но сертификат ещё валиден и mTLS-запрос ротации проходит.
    """
    initial_cert_pem, initial_key_pem = server.issue_initial_client_certificate("turnstile-01")
    initial_cert_path = _write(str(tmp_path / "initial_cert.pem"), initial_cert_pem)
    initial_key_path = _write(str(tmp_path / "initial_key.pem"), initial_key_pem)
    server.working_cert_validity_days = 1

    rest = RestClient(server.base_url, ca_bundle=ca_bundle_path, timeout=5.0)
    subject = CertificateSubject(organization="Школа №1", organizational_units=["Корпус 1"], common_name="turnstile-01")
    manager = CertificateManager(
        rest, cert_dir=str(tmp_path / "certs"), subject=subject,
        initial_cert_path=initial_cert_path, initial_key_path=initial_key_path,
        rotation_threshold_fraction=0.5,
    )
    manager.ensure_bootstrapped()
    old_cert = open(manager._working_cert_path).read()

    # notBefore выдан с суточным "запасом назад" (см. sign_csr) — при
    # 2-суточной валидности уже сразу после выдачи остаётся <=50% срока.
    rotated = manager.maybe_rotate()

    assert rotated is True
    assert len(server.cert_requests) == 2
    new_cert = open(manager._working_cert_path).read()
    assert new_cert != old_cert

    # Новый сертификат должен реально работать против сервера.
    backend = BackendClient(rest_client=rest)
    assert backend.check_connectivity() in (True, False)  # не должно бросать исключение
    backend.patch_accesspoint(mac="aa:bb:cc:dd:ee:ff", ip="10.0.0.5", cpuid="cafebabe")
    assert server.accesspoint_data["mac"] == "aa:bb:cc:dd:ee:ff"


def test_bootstrap_without_client_certificate_is_rejected_by_server(server, ca_bundle_path):
    """Без mTLS-сертификата сервер обязан отклонить соединение (§6.2)."""
    rest = RestClient(server.base_url, ca_bundle=ca_bundle_path, timeout=5.0)
    backend = BackendClient(rest_client=rest)

    with pytest.raises(BackendApiError):
        backend.get_keys()


# ---------------------------------------------------------------------------
# 2. Полный обход ресурсов controller/v1/* через реальный HTTP+mTLS
# ---------------------------------------------------------------------------

@pytest.fixture
def bootstrapped_backend(server, ca_bundle_path, tmp_path):
    """BackendClient с уже активным рабочим mTLS-сертификатом на реальном сервере."""
    initial_cert_pem, initial_key_pem = server.issue_initial_client_certificate("turnstile-01")
    initial_cert_path = _write(str(tmp_path / "initial_cert.pem"), initial_cert_pem)
    initial_key_path = _write(str(tmp_path / "initial_key.pem"), initial_key_pem)

    rest = RestClient(server.base_url, ca_bundle=ca_bundle_path, timeout=5.0)
    subject = CertificateSubject(organization="Школа №1", organizational_units=["Корпус 1"], common_name="turnstile-01")
    manager = CertificateManager(
        rest, cert_dir=str(tmp_path / "certs"), subject=subject,
        initial_cert_path=initial_cert_path, initial_key_path=initial_key_path,
    )
    manager.ensure_bootstrapped()
    return BackendClient(rest_client=rest)


def test_get_keys_roundtrip(server, bootstrapped_backend):
    server.keys_response = {
        "status": "ok", "quantity": 1,
        "keys": [{"num": 5, "public": "aa" * 32, "shared": "bb" * 16, "dynamic": "cc" * 32}],
    }
    keys = bootstrapped_backend.get_keys()
    assert keys[0]["num"] == 5


def test_access_list_roundtrip_with_update_flag(server, bootstrapped_backend):
    server.access_response = {
        "status": "ok", "update": 0, "dynamic_key": "0123456789abcdef0123456789abcdef",
        "id": [{"type": "maxid", "quantity": 1, "list": ["1234567"]}],
    }

    response = bootstrapped_backend.get_access_list(update=0)

    assert server.access_requests == [0]
    assert response["id"][0]["list"] == ["1234567"]


def test_accesspoint_patch_then_get_roundtrip(server, bootstrapped_backend):
    bootstrapped_backend.patch_accesspoint(mac="00:11:22:33:44:55", ip="10.1.1.1", cpuid="1234")

    result = bootstrapped_backend.get_accesspoint()

    assert result["mac"] == "00:11:22:33:44:55"
    assert result["ip"] == "10.1.1.1"


def test_event_put_then_get_last_event_roundtrip(server, bootstrapped_backend):
    event = PassageEvent(
        event_id=17, stime=time.time(), event_type="access", direction="in",
        token_type="maxid", token="1234567", result="pass", severity="info",
    )

    bootstrapped_backend.put_event(event)
    last = bootstrapped_backend.get_last_event()

    assert last["event_id"] == 17
    assert server.events[0]["token"] == "1234567"


def test_send_events_batch_roundtrip(server, bootstrapped_backend):
    events = [
        PassageEvent(event_id=1, event_type="access", token_type="maxid", token="1", result="pass"),
        PassageEvent(event_id=2, event_type="access", token_type="cardid_h", token="2", result="pass"),
    ]
    ok = bootstrapped_backend.send_events(events)

    assert ok is True
    assert len(server.events) == 2


# ---------------------------------------------------------------------------
# 3. Полная сборка приложения (build_application) против фейкового сервера
# ---------------------------------------------------------------------------

@pytest.fixture
def real_config_dict():
    """Загрузить реальный app/config.yml как основу для тестового конфига."""
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config_path = os.path.join(repo_root, "config.yml")
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f), config_path


def test_build_application_against_fake_backend(server, ca_bundle_path, tmp_path, real_config_dict):
    """
    Полная сборка LGTUApplication с конфигом, указывающим на фейковый
    backend вместо api.pass.lipetsk.ru — конфигурация НЕ хардкодится в коде,
    вся адресация идёт из config.yml (см. backend.base_url/ca_bundle/cert.*).
    """
    config, _ = real_config_dict

    initial_cert_pem, initial_key_pem = server.issue_initial_client_certificate("turnstile-01")
    _write(str(tmp_path / "initial_cert.pem"), initial_cert_pem)
    _write(str(tmp_path / "initial_key.pem"), initial_key_pem)

    config["backend"]["base_url"] = server.base_url
    config["backend"]["ca_bundle"] = ca_bundle_path
    # Для фейкового сервера используем стандартные пути /resource/action.
    config["backend"].pop("endpoint_map", None)
    config["backend"].pop("method_map", None)
    config["backend"]["cert"]["cert_dir"] = "certs"
    config["backend"]["cert"]["initial_cert_path"] = "initial_cert.pem"
    config["backend"]["cert"]["initial_key_path"] = "initial_key.pem"

    test_config_path = tmp_path / "config.yml"
    with open(test_config_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(config, f)

    from app.infrastructure.bootstrap import build_application

    server.keys_response = {
        "status": "ok", "quantity": 1,
        "keys": [{"num": 1, "public": "aa" * 32, "shared": "bb" * 16, "dynamic": "cc" * 32}],
    }

    app = build_application(str(test_config_path))

    assert app is not None
    # Сертификат должен быть выпущен настоящим (фейковым) backend'ом при сборке.
    assert len(server.cert_requests) == 1
    assert os.path.exists(str(tmp_path / "certs" / "working_cert.pem"))

    # Периодические сервисы должны успешно тикнуть против фейкового сервера.
    for service in app._periodic_services:
        service.tick(time.time())

    # Ключи QR-кодов хранятся только в оперативной памяти (ТЗ), на диск не
    # пишутся — проверяем, что набор ключей с num=1 загружен в QRDecoder.
    assert 1 in app._qr_decoder._keys
    assert server.accesspoint_data.get("mac")
