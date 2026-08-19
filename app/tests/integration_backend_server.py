"""
Локальный фейковый backend-сервер для интеграционных тестов (без сети и без
реального api.pass.lipetsk.ru).

В отличие от unit-тестов (test_backend_*.py), которые подменяют
``requests.Session``, здесь поднимается настоящий HTTPS-сервер с mTLS на
127.0.0.1 со случайным свободным портом, и клиент (``RestClient``/
``BackendClient``/``CertificateManager``) обращается к нему по-настоящему —
через реальный TLS-хендшейк, реальную проверку клиентского сертификата и
реальный HTTP-протокол. Это проверяет весь путь целиком, а не только логику
формирования запроса.

Реализует минимальный поднабор ресурсов ветви ``controller`` (§6.5 ТЗ):
keys, cert, access, accesspoint, event — достаточный для сборки
``build_application()`` и работы периодических сервисов.
"""
from __future__ import annotations

import datetime
import json
import ssl
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Optional

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


# ---------------------------------------------------------------------------
# Генерация тестового CA и сертификатов (замена реального CA бэкенда)
# ---------------------------------------------------------------------------

def generate_ca() -> tuple[str, Any, Any]:
    """Сгенерировать тестовый CA. Возвращает (ca_cert_pem, ca_cert, ca_key)."""
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Test SCUD CA")])
    now = datetime.datetime.now(datetime.timezone.utc)
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=False,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False,
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )
    ca_cert_pem = ca_cert.public_bytes(serialization.Encoding.PEM).decode("utf-8")
    return ca_cert_pem, ca_cert, ca_key


def issue_certificate(
    ca_cert, ca_key, common_name: str, days: int = 90,
    san_dns: Optional[list[str]] = None, san_ip: Optional[list[str]] = None,
) -> tuple[str, str]:
    """
    Выпустить сертификат, подписанный тестовым CA. Возвращает (cert_pem, key_pem).

    Используется и для сервера (с SAN на 127.0.0.1/localhost), и для
    первичного клиентского сертификата контроллера (аналог загруженного
    вручную первичного сертификата, §5.4.1).
    """
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    now = datetime.datetime.now(datetime.timezone.utc)

    builder = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=days))
    )
    if san_dns or san_ip:
        san_entries = [x509.DNSName(d) for d in (san_dns or [])]
        san_entries += [x509.IPAddress(__import__("ipaddress").ip_address(ip)) for ip in (san_ip or [])]
        builder = builder.add_extension(x509.SubjectAlternativeName(san_entries), critical=False)

    builder = (
        builder
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=True,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=False,
        )
        .add_extension(
            x509.ExtendedKeyUsage([
                x509.ExtendedKeyUsageOID.SERVER_AUTH,
                x509.ExtendedKeyUsageOID.CLIENT_AUTH,
            ]),
            critical=False,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False,
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
            critical=False,
        )
    )

    cert = builder.sign(ca_key, hashes.SHA256())

    cert_pem = cert.public_bytes(serialization.Encoding.PEM).decode("utf-8")
    key_pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption(),
    ).decode("utf-8")
    return cert_pem, key_pem


def sign_csr(ca_cert, ca_key, csr_pem: str, days: int = 90) -> str:
    """Подписать CSR тестовым CA (реализация ресурса cert/get на сервере)."""
    csr = x509.load_pem_x509_csr(csr_pem.encode("utf-8"))
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(csr.subject)
        .issuer_name(ca_cert.subject)
        .public_key(csr.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=days))
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=True,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=False,
        )
        .add_extension(
            x509.ExtendedKeyUsage([x509.ExtendedKeyUsageOID.CLIENT_AUTH]),
            critical=False,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(csr.public_key()), critical=False,
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )
    return cert.public_bytes(serialization.Encoding.PEM).decode("utf-8")


# ---------------------------------------------------------------------------
# Фейковый backend-сервер
# ---------------------------------------------------------------------------

class FakeBackendServer:
    """
    Поднимает настоящий HTTPS+mTLS сервер на 127.0.0.1 со случайным портом,
    реализующий минимальный набор ресурсов ветви ``controller`` (§6.5 ТЗ) в
    памяти (без реальной БД — этого достаточно для интеграционных тестов
    app, которые проверяют только сторону контроллера).
    """

    def __init__(self):
        self.ca_cert_pem, self._ca_cert, self._ca_key = generate_ca()
        server_cert_pem, server_key_pem = issue_certificate(
            self._ca_cert, self._ca_key, "test-backend",
            san_dns=["localhost"], san_ip=["127.0.0.1"],
        )
        self._server_cert_pem = server_cert_pem
        self._server_key_pem = server_key_pem

        # Состояние "БД" бэкенда в памяти.
        self.keys_response = {"status": "ok", "quantity": 0, "keys": []}
        self.access_response = {"status": "ok", "update": 0, "id": []}
        self.access_requests: list[int] = []  # история переданных update-флагов
        self.accesspoint_data: dict[str, str] = {}
        self.events: list[dict] = []
        self.cert_requests: list[str] = []

        self._httpd: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    @property
    def base_url(self) -> str:
        host, port = self._httpd.server_address
        return f"https://127.0.0.1:{port}"

    def start(self) -> None:
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):  # заглушить стандартный access-лог
                pass

            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                raw_body = self.rfile.read(length) if length else b""
                try:
                    payload = json.loads(raw_body) if raw_body and raw_body != b"null" else {}
                except json.JSONDecodeError:
                    payload = {}

                parts = self.path.strip("/").split("/")
                # /controller/v1/<resource>/<action>
                if len(parts) != 4 or parts[0] != "controller" or parts[1] != "v1":
                    self._respond(404, {"status": "error", "description": "unknown resource"})
                    return
                resource, action = parts[2], parts[3]
                try:
                    response = server._dispatch(resource, action, payload)
                except _HttpError as exc:
                    self._respond(exc.status, {"status": "error", "description": str(exc)})
                    return
                self._respond(200, response)

            def _respond(self, status: int, body: dict) -> None:
                data = json.dumps(body).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)

        ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ssl_context.load_cert_chain(
            certfile=_write_temp(self._server_cert_pem), keyfile=_write_temp(self._server_key_pem),
        )
        ssl_context.verify_mode = ssl.CERT_REQUIRED
        ssl_context.load_verify_locations(cadata=self.ca_cert_pem)

        self._httpd.socket = ssl_context.wrap_socket(self._httpd.socket, server_side=True)

        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def issue_initial_client_certificate(self, common_name: str = "turnstile-test") -> tuple[str, str]:
        """Выпустить 'первичный' клиентский сертификат (аналог ручной загрузки, §5.4.1)."""
        return issue_certificate(self._ca_cert, self._ca_key, common_name, days=10)

    def _dispatch(self, resource: str, action: str, payload: dict) -> dict:
        key = (resource, action)
        if key == ("keys", "get"):
            return self.keys_response
        if key == ("cert", "get"):
            csr_pem = payload.get("csr")
            if not csr_pem:
                raise _HttpError(400, "csr required")
            self.cert_requests.append(csr_pem)
            crt_pem = sign_csr(self._ca_cert, self._ca_key, csr_pem)
            return {"status": "ok", "crt": crt_pem}
        if key == ("access", "get"):
            self.access_requests.append(payload.get("update", 1))
            return self.access_response
        if key == ("accesspoint", "get"):
            if not self.accesspoint_data:
                raise _HttpError(404, "accesspoint not registered")
            return {"status": "ok", **self.accesspoint_data}
        if key == ("accesspoint", "patch"):
            self.accesspoint_data = {
                "mac": payload.get("mac"), "ip": payload.get("ip"), "cpuid": payload.get("cpuid"),
            }
            return {"status": "ok"}
        if key == ("event", "put"):
            self.events.append(payload)
            return {"status": "ok"}
        if key == ("event", "get"):
            if not self.events:
                return {"status": "ok", "event_id": 0}
            last = self.events[-1]
            return {"status": "ok", "event_id": last.get("event_id", 0), "stime": last.get("stime", "")}
        raise _HttpError(404, f"unknown resource/action: {resource}/{action}")


class _HttpError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def _write_temp(content: str) -> str:
    import tempfile
    fd, path = tempfile.mkstemp(suffix=".pem")
    with __import__("os").fdopen(fd, "w") as f:
        f.write(content)
    return path
