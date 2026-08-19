"""Тесты жизненного цикла mTLS-сертификата контроллера (п. 5.4.1 ТЗ)."""
import hashlib
import os

import pytest

from app.infrastructure.backend.certificate_manager import CertificateManager, CertificateSubject
from app.infrastructure.backend.rest_client import BackendApiError


class FakeRestClient:
    """Подмена RestClient: подписывает любой CSR фиктивным 'сертификатом'."""

    def __init__(self, fail: bool = False):
        self.fail = fail
        self.calls = []
        self.active_cert = None

    def call(self, resource, action, payload=None):
        self.calls.append((resource, action, payload))
        if self.fail:
            raise BackendApiError("cert/get failed")
        assert resource == "cert" and action == "get"
        csr_pem = payload["csr"]
        # "Подписываем" CSR - фиктивный PEM, уникальный для каждого CSR
        # (хеш всего CSR, а не одной строки, т.к. у RSA-CSR с одинаковым
        # Subject первые строки base64 могут совпадать между разными ключами).
        digest = hashlib.sha256(csr_pem.encode("utf-8")).hexdigest()
        crt_pem = f"-----BEGIN CERTIFICATE-----\n{digest}\n-----END CERTIFICATE-----\n"
        return {"status": "ok", "crt": crt_pem}

    def set_client_cert(self, cert_path, key_path):
        self.active_cert = (cert_path, key_path)

    def set_ca_bundle(self, ca_bundle):
        self.ca_bundle = ca_bundle


@pytest.fixture
def subject():
    return CertificateSubject(organization="ОО", organizational_units=["Корпус 1"], common_name="turnstile-01")


@pytest.fixture
def initial_cert_files(tmp_path):
    cert_path = tmp_path / "initial_cert.pem"
    key_path = tmp_path / "initial_key.pem"
    cert_path.write_text("dummy initial cert")
    key_path.write_text("dummy initial key")
    return str(cert_path), str(key_path)


def test_ensure_bootstrapped_without_initial_cert_does_nothing(tmp_path, subject):
    rest = FakeRestClient()
    manager = CertificateManager(rest, cert_dir=str(tmp_path / "certs"), subject=subject)

    manager.ensure_bootstrapped()

    assert not manager.has_working_certificate
    assert rest.calls == []


def test_ensure_bootstrapped_exchanges_initial_for_working_certificate(tmp_path, subject, initial_cert_files):
    initial_cert_path, initial_key_path = initial_cert_files
    rest = FakeRestClient()
    manager = CertificateManager(
        rest,
        cert_dir=str(tmp_path / "certs"),
        subject=subject,
        initial_cert_path=initial_cert_path,
        initial_key_path=initial_key_path,
    )

    manager.ensure_bootstrapped()

    assert manager.has_working_certificate
    # Первичный сертификат должен быть удалён с контроллера (п. 5.4.1).
    assert not os.path.exists(initial_cert_path)
    assert not os.path.exists(initial_key_path)
    # cert/get был вызван один раз, и клиент переключился на рабочий сертификат.
    assert len(rest.calls) == 1
    assert rest.active_cert == (manager._working_cert_path, manager._working_key_path)


def test_ensure_bootstrapped_is_idempotent(tmp_path, subject, initial_cert_files):
    initial_cert_path, initial_key_path = initial_cert_files
    rest = FakeRestClient()
    manager = CertificateManager(
        rest, cert_dir=str(tmp_path / "certs"), subject=subject,
        initial_cert_path=initial_cert_path, initial_key_path=initial_key_path,
    )
    manager.ensure_bootstrapped()
    calls_after_first = len(rest.calls)

    # Повторный вызов не должен снова обращаться к бэкенду, т.к. рабочий
    # сертификат уже есть.
    manager.ensure_bootstrapped()
    assert len(rest.calls) == calls_after_first


def test_maybe_rotate_does_nothing_before_rotation_period(tmp_path, subject, initial_cert_files):
    initial_cert_path, initial_key_path = initial_cert_files
    rest = FakeRestClient()
    now = [1_700_000_000.0]
    manager = CertificateManager(
        rest, cert_dir=str(tmp_path / "certs"), subject=subject,
        initial_cert_path=initial_cert_path, initial_key_path=initial_key_path,
        rotation_period_days=30, clock=lambda: now[0],
    )
    manager.ensure_bootstrapped()
    calls_after_bootstrap = len(rest.calls)

    now[0] += 10 * 86400  # только 10 суток прошло
    rotated = manager.maybe_rotate(now[0])

    assert rotated is False
    assert len(rest.calls) == calls_after_bootstrap


def test_maybe_rotate_after_period_generates_new_certificate(tmp_path, subject, initial_cert_files):
    initial_cert_path, initial_key_path = initial_cert_files
    rest = FakeRestClient()
    now = [1_700_000_000.0]
    manager = CertificateManager(
        rest, cert_dir=str(tmp_path / "certs"), subject=subject,
        initial_cert_path=initial_cert_path, initial_key_path=initial_key_path,
        rotation_period_days=30, clock=lambda: now[0],
    )
    manager.ensure_bootstrapped()
    old_cert_content = open(manager._working_cert_path).read()
    calls_after_bootstrap = len(rest.calls)

    now[0] += 31 * 86400
    rotated = manager.maybe_rotate(now[0])

    assert rotated is True
    assert len(rest.calls) == calls_after_bootstrap + 1
    # Старые файлы ротации не должны оставаться на диске.
    assert not os.path.exists(manager._working_cert_path + ".old")
    assert not os.path.exists(manager._working_key_path + ".old")
    new_cert_content = open(manager._working_cert_path).read()
    assert new_cert_content != old_cert_content


def test_on_exchange_success_callback_called_after_bootstrap_and_rotation(tmp_path, subject, initial_cert_files):
    initial_cert_path, initial_key_path = initial_cert_files
    rest = FakeRestClient()
    now = [1_700_000_000.0]
    calls = []
    manager = CertificateManager(
        rest, cert_dir=str(tmp_path / "certs"), subject=subject,
        initial_cert_path=initial_cert_path, initial_key_path=initial_key_path,
        rotation_period_days=30, clock=lambda: now[0],
        on_exchange_success=lambda: calls.append(now[0]),
    )

    manager.ensure_bootstrapped()
    assert calls == [now[0]]

    now[0] += 31 * 86400
    manager.maybe_rotate(now[0])
    assert calls == [1_700_000_000.0, now[0]]


def test_maybe_rotate_rolls_back_on_backend_failure(tmp_path, subject, initial_cert_files):
    initial_cert_path, initial_key_path = initial_cert_files
    rest = FakeRestClient()
    now = [1_700_000_000.0]
    manager = CertificateManager(
        rest, cert_dir=str(tmp_path / "certs"), subject=subject,
        initial_cert_path=initial_cert_path, initial_key_path=initial_key_path,
        rotation_period_days=30, clock=lambda: now[0],
    )
    manager.ensure_bootstrapped()
    old_cert_content = open(manager._working_cert_path).read()

    rest.fail = True
    now[0] += 31 * 86400
    rotated = manager.maybe_rotate(now[0])

    assert rotated is False
    # Сертификат должен остаться работоспособным (откат).
    assert manager.has_working_certificate
    assert open(manager._working_cert_path).read() == old_cert_content


# ── KMS Bootstrap ──


class FakeKmsSession:
    """Подмена HTTP-сессии для запросов к KMS /bootstrap."""

    def __init__(self, cert_pem="---CERT---", key_pem="---KEY---",
                 ca_pem="---CA---", status_code=200, fail=False):
        self.cert_pem = cert_pem
        self.key_pem = key_pem
        self.ca_pem = ca_pem
        self.status_code = status_code
        self.fail = fail
        self.calls = []
        self.verify = True

    def get(self, url, **kwargs):
        self.calls.append(url)
        if self.fail:
            raise ConnectionError("KMS unreachable")
        return _FakeResponse(
            status_code=self.status_code,
            json_data={
                "bootstrap": {"crt": self.cert_pem, "private_key": self.key_pem},
                "ca": {"crt": self.ca_pem},
            },
        )


class _FakeResponse:
    def __init__(self, status_code, json_data):
        self.status_code = status_code
        self._json = json_data

    def json(self):
        return self._json


def test_kms_bootstrap_fetches_initial_cert_when_missing(tmp_path, subject):
    """Если нет первичного сертификата и задан kms_url — получаем с KMS."""
    rest = FakeRestClient()
    kms = FakeKmsSession(cert_pem="KMS-CERT-PEM", key_pem="KMS-KEY-PEM", ca_pem="KMS-CA-PEM")
    cert_dir = str(tmp_path / "certs")
    manager = CertificateManager(
        rest, cert_dir=cert_dir, subject=subject,
        kms_url="https://kms.example.com", kms_session=kms,
    )

    manager.ensure_bootstrapped()

    # KMS был вызван.
    assert len(kms.calls) == 1
    assert kms.calls[0] == "https://kms.example.com/bootstrap"
    # Первичный сертификат получен → обмен на рабочий через cert/get.
    assert manager.has_working_certificate
    assert len(rest.calls) == 1
    # Первичный сертификат удалён после обмена (как при ручной загрузке).
    assert not os.path.exists(manager._initial_cert_path)
    assert not os.path.exists(manager._initial_key_path)
    # CA от KMS сохранён и установлен в RestClient для проверки controller.
    ca_path = os.path.join(cert_dir, "ca.pem")
    assert os.path.exists(ca_path)
    assert open(ca_path).read() == "KMS-CA-PEM"
    assert rest.ca_bundle == ca_path


def test_kms_bootstrap_not_called_when_initial_exists(tmp_path, subject, initial_cert_files):
    """Если первичный сертификат есть на диске — KMS не вызывается."""
    initial_cert_path, initial_key_path = initial_cert_files
    rest = FakeRestClient()
    kms = FakeKmsSession()
    manager = CertificateManager(
        rest, cert_dir=str(tmp_path / "certs"), subject=subject,
        initial_cert_path=initial_cert_path, initial_key_path=initial_key_path,
        kms_url="https://kms.example.com", kms_session=kms,
    )

    manager.ensure_bootstrapped()

    assert kms.calls == []
    assert manager.has_working_certificate


def test_kms_bootstrap_not_called_when_working_cert_exists(tmp_path, subject, initial_cert_files):
    """Если рабочий сертификат уже есть — ни KMS, ни cert/get не вызываются."""
    initial_cert_path, initial_key_path = initial_cert_files
    rest = FakeRestClient()
    kms = FakeKmsSession()
    manager = CertificateManager(
        rest, cert_dir=str(tmp_path / "certs"), subject=subject,
        initial_cert_path=initial_cert_path, initial_key_path=initial_key_path,
        kms_url="https://kms.example.com", kms_session=kms,
    )
    manager.ensure_bootstrapped()
    calls_after_first = len(rest.calls)

    manager.ensure_bootstrapped()

    assert kms.calls == []
    assert len(rest.calls) == calls_after_first


def test_kms_bootstrap_network_error_falls_back_to_warning(tmp_path, subject):
    """Если KMS недоступен — warning, не crash."""
    rest = FakeRestClient()
    kms = FakeKmsSession(fail=True)
    manager = CertificateManager(
        rest, cert_dir=str(tmp_path / "certs"), subject=subject,
        kms_url="https://kms.example.com", kms_session=kms,
    )

    manager.ensure_bootstrapped()

    assert not manager.has_working_certificate
    assert rest.calls == []


def test_kms_bootstrap_http_error_falls_back_to_warning(tmp_path, subject):
    """Если KMS возвращает ошибку HTTP — warning, не crash."""
    rest = FakeRestClient()
    kms = FakeKmsSession(status_code=500)
    manager = CertificateManager(
        rest, cert_dir=str(tmp_path / "certs"), subject=subject,
        kms_url="https://kms.example.com", kms_session=kms,
    )

    manager.ensure_bootstrapped()

    assert not manager.has_working_certificate


def test_kms_bootstrap_no_kms_url_does_nothing(tmp_path, subject):
    """Без kms_url и без первичного сертификата — только warning."""
    rest = FakeRestClient()
    manager = CertificateManager(
        rest, cert_dir=str(tmp_path / "certs"), subject=subject,
    )

    manager.ensure_bootstrapped()

    assert not manager.has_working_certificate
    assert rest.calls == []
