"""Тесты жизненного цикла mTLS-сертификата контроллера (п. 5.4.1 ТЗ)."""
import os
from datetime import datetime, timedelta, timezone

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.infrastructure.backend.certificate_manager import (
    CertificateManager,
    CertificateSubject,
)
from app.infrastructure.backend.rest_client import BackendApiError

# Реальная валидность рабочего сертификата, выдаваемого бэкендом (см. docstring
# CertificateManager) — используется как дефолт в FakeRestClient, чтобы тесты
# ротации проверяли настоящий разбор notBefore/notAfter, а не фиктивный PEM.
CERT_VALIDITY_DAYS_DEFAULT = 90


def _sign_csr(csr_pem: str, valid_from: datetime, valid_until: datetime) -> str:
    """Подписать CSR самоподписанным "сертификатом" с заданным сроком действия.

    Личность издателя тут не важна — тесты не устанавливают реальных TLS-
    соединений, только проверяют разбор notBefore/notAfter и логику ротации.
    """
    csr = x509.load_pem_x509_csr(csr_pem.encode("utf-8"))
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    cert = (
        x509.CertificateBuilder()
        .subject_name(csr.subject)
        .issuer_name(csr.subject)
        .public_key(csr.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(valid_from)
        .not_valid_after(valid_until)
        .sign(ca_key, hashes.SHA256())
    )
    return cert.public_bytes(serialization.Encoding.PEM).decode("utf-8")


class FakeRestClient:
    """Подмена RestClient: подписывает любой CSR настоящим X.509-сертификатом
    с настраиваемым сроком действия (для проверки логики ротации по порогу)."""

    def __init__(self, fail: bool = False, cert_validity_days: float = CERT_VALIDITY_DAYS_DEFAULT, clock=None):
        self.fail = fail
        self.calls = []
        self.active_cert = None
        self.cert_validity_days = cert_validity_days
        # Тот же clock, что передаётся в CertificateManager — чтобы "время
        # выдачи" сертификата совпадало с текущим временем теста.
        self._clock = clock or (lambda: 1_700_000_000.0)

    def call(self, resource, action, payload=None):
        self.calls.append((resource, action, payload))
        if self.fail:
            raise BackendApiError("cert/get failed")
        assert resource == "cert" and action == "get"
        csr_pem = payload["csr"]
        valid_from = datetime.fromtimestamp(self._clock(), tz=timezone.utc)
        valid_until = valid_from + timedelta(days=self.cert_validity_days)
        crt_pem = _sign_csr(csr_pem, valid_from, valid_until)
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


# ── Ротация по остатку срока действия (не по фиксированному расписанию) ──


def test_maybe_rotate_does_nothing_while_remaining_lifetime_above_threshold(tmp_path, subject, initial_cert_files):
    initial_cert_path, initial_key_path = initial_cert_files
    now = [1_700_000_000.0]
    rest = FakeRestClient(clock=lambda: now[0])
    manager = CertificateManager(
        rest, cert_dir=str(tmp_path / "certs"), subject=subject,
        initial_cert_path=initial_cert_path, initial_key_path=initial_key_path,
        rotation_threshold_fraction=0.5, clock=lambda: now[0],
    )
    manager.ensure_bootstrapped()
    calls_after_bootstrap = len(rest.calls)

    now[0] += 10 * 86400  # осталось 80/90 суток (>50%) — рано
    rotated = manager.maybe_rotate(now[0])

    assert rotated is False
    assert len(rest.calls) == calls_after_bootstrap


def test_maybe_rotate_triggers_when_remaining_lifetime_below_threshold(tmp_path, subject, initial_cert_files):
    initial_cert_path, initial_key_path = initial_cert_files
    now = [1_700_000_000.0]
    rest = FakeRestClient(clock=lambda: now[0])
    manager = CertificateManager(
        rest, cert_dir=str(tmp_path / "certs"), subject=subject,
        initial_cert_path=initial_cert_path, initial_key_path=initial_key_path,
        rotation_threshold_fraction=0.5, clock=lambda: now[0],
    )
    manager.ensure_bootstrapped()
    old_cert_content = open(manager._working_cert_path).read()
    calls_after_bootstrap = len(rest.calls)

    now[0] += 46 * 86400  # осталось 44/90 суток (<50%) — пора
    rotated = manager.maybe_rotate(now[0])

    assert rotated is True
    assert len(rest.calls) == calls_after_bootstrap + 1
    # Старые файлы ротации не должны оставаться на диске.
    assert not os.path.exists(manager._working_cert_path + ".old")
    assert not os.path.exists(manager._working_key_path + ".old")
    new_cert_content = open(manager._working_cert_path).read()
    assert new_cert_content != old_cert_content
    # После успешной ротации новый сертификат снова "молодой" — отметка
    # последней попытки ротации (в памяти, на диск не пишется) сброшена.
    assert manager._last_rotation_attempt is None


def test_maybe_rotate_does_not_retry_within_retry_interval(tmp_path, subject, initial_cert_files):
    """Если обмен провалился, повторная попытка раньше retry_interval игнорируется."""
    initial_cert_path, initial_key_path = initial_cert_files
    now = [1_700_000_000.0]
    rest = FakeRestClient(clock=lambda: now[0])
    manager = CertificateManager(
        rest, cert_dir=str(tmp_path / "certs"), subject=subject,
        initial_cert_path=initial_cert_path, initial_key_path=initial_key_path,
        rotation_threshold_fraction=0.5, rotation_retry_interval_days=1, clock=lambda: now[0],
    )
    manager.ensure_bootstrapped()
    rest.fail = True

    now[0] += 46 * 86400  # порог пройден
    first_attempt = manager.maybe_rotate(now[0])
    calls_after_first_attempt = len(rest.calls)

    now[0] += 3600  # прошёл всего час — рано для повторной попытки
    second_attempt = manager.maybe_rotate(now[0])

    assert first_attempt is False
    assert second_attempt is False
    # Второй вызов НЕ должен был снова стучаться в бэкенд.
    assert len(rest.calls) == calls_after_first_attempt


def test_maybe_rotate_retries_daily_until_success(tmp_path, subject, initial_cert_files):
    """Пока обмен не удастся — повтор раз в retry_interval, по кругу."""
    initial_cert_path, initial_key_path = initial_cert_files
    now = [1_700_000_000.0]
    rest = FakeRestClient(clock=lambda: now[0])
    manager = CertificateManager(
        rest, cert_dir=str(tmp_path / "certs"), subject=subject,
        initial_cert_path=initial_cert_path, initial_key_path=initial_key_path,
        rotation_threshold_fraction=0.5, rotation_retry_interval_days=1, clock=lambda: now[0],
    )
    manager.ensure_bootstrapped()
    rest.fail = True

    now[0] += 46 * 86400  # порог пройден, но бэкенд недоступен
    assert manager.maybe_rotate(now[0]) is False

    now[0] += 86400  # сутки спустя — бэкенд снова доступен
    rest.fail = False
    rotated = manager.maybe_rotate(now[0])

    assert rotated is True
    assert manager.has_working_certificate


def test_on_exchange_success_callback_called_after_bootstrap_and_rotation(tmp_path, subject, initial_cert_files):
    initial_cert_path, initial_key_path = initial_cert_files
    now = [1_700_000_000.0]
    rest = FakeRestClient(clock=lambda: now[0])
    calls = []
    manager = CertificateManager(
        rest, cert_dir=str(tmp_path / "certs"), subject=subject,
        initial_cert_path=initial_cert_path, initial_key_path=initial_key_path,
        rotation_threshold_fraction=0.5, clock=lambda: now[0],
        on_exchange_success=lambda: calls.append(now[0]),
    )

    manager.ensure_bootstrapped()
    assert calls == [now[0]]

    now[0] += 46 * 86400
    manager.maybe_rotate(now[0])
    assert calls == [1_700_000_000.0, now[0]]


def test_maybe_rotate_rolls_back_on_backend_failure(tmp_path, subject, initial_cert_files):
    initial_cert_path, initial_key_path = initial_cert_files
    now = [1_700_000_000.0]
    rest = FakeRestClient(clock=lambda: now[0])
    manager = CertificateManager(
        rest, cert_dir=str(tmp_path / "certs"), subject=subject,
        initial_cert_path=initial_cert_path, initial_key_path=initial_key_path,
        rotation_threshold_fraction=0.5, clock=lambda: now[0],
    )
    manager.ensure_bootstrapped()
    old_cert_content = open(manager._working_cert_path).read()

    rest.fail = True
    now[0] += 46 * 86400
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
