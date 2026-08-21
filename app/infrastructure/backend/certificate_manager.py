"""
Управление жизненным циклом клиентского mTLS-сертификата контроллера (п. 5.4.1 ТЗ).

Схема:
1. Если нет ни рабочего, ни первичного сертификата и задан ``kms_url`` —
   контроллер автоматически запрашивает первичный сертификат с KMS-сервера
   (``POST kms_url/bootstrap``). Ответ содержит cert/key — они сохраняются
   на диск как первичный сертификат.
2. При первом подключении генерируется рабочая ключевая пара и CSR с тем же
   Subject, запрос подписывается бэкендом (``cert/get``) через mTLS с
   первичным сертификатом; полученный рабочий сертификат действует 90 суток.
3. Первичный ключ/сертификат удаляются на контроллере (и на бэкенде).
4. Ротация запускается не по фиксированному расписанию, а когда от реального
   срока действия рабочего сертификата (берётся из самого сертификата —
   ``notBefore``/``notAfter``, а не из локально запомненной даты выдачи)
   остаётся меньше заданной доли (``rotation_threshold_fraction``, по
   умолчанию половина). Как только порог пройден, контроллер пробует
   обменять сертификат не чаще раза в ``rotation_retry_interval_days``
   (по умолчанию раз в сутки) — и так по кругу, пока обмен не удастся;
   при успехе новый сертификат снова "молодой", и цикл проверки начинается
   заново. Это ограничивает и число запросов к бэкенду, и число перезаписей
   working_cert/working_key на диске (ограниченный ресурс перезаписи flash),
   в отличие от повторной попытки на каждой итерации основного цикла.

Классы
------
- CertificateManager: управляет CSR, обменом с бэкендом и ротацией.
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from datetime import timezone
from typing import Any, Optional

try:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    CRYPTOGRAPHY_AVAILABLE = True
except ImportError:
    CRYPTOGRAPHY_AVAILABLE = False

try:
    import requests as _requests_lib
    _REQUESTS_AVAILABLE = True
except ImportError:
    _requests_lib = None  # type: ignore[assignment]
    _REQUESTS_AVAILABLE = False

from app.infrastructure.backend.rest_client import (
    DEFAULT_USER_AGENT,
    BackendApiError,
    RestClient,
)

logger = logging.getLogger(__name__)

ROTATION_THRESHOLD_FRACTION_DEFAULT = 0.5
ROTATION_RETRY_INTERVAL_DAYS_DEFAULT = 1


@dataclass
class CertificateSubject:
    """Поля Subject клиентского сертификата (п. 5.4.1: O, OU (может быть несколько), CN)."""
    organization: str
    organizational_units: list[str]
    common_name: str


class CertificateManager:
    """Управляет первичным/рабочим сертификатом контроллера и его ротацией."""

    def __init__(
        self,
        rest_client: RestClient,
        cert_dir: str,
        subject: CertificateSubject,
        initial_cert_path: Optional[str] = None,
        initial_key_path: Optional[str] = None,
        rotation_threshold_fraction: float = ROTATION_THRESHOLD_FRACTION_DEFAULT,
        rotation_retry_interval_days: float = ROTATION_RETRY_INTERVAL_DAYS_DEFAULT,
        clock: Optional[callable] = None,
        on_exchange_success: Optional[callable] = None,
        rsa_key_size: int = 2048,
        kms_url: Optional[str] = None,
        ca_bundle: Optional[str] = None,
        kms_session: Optional[Any] = None,
        access_point_id: Optional[str] = None,
        user_agent: str = DEFAULT_USER_AGENT,
    ) -> None:
        if not CRYPTOGRAPHY_AVAILABLE:
            raise ImportError("Модуль cryptography не установлен. Установите: pip install cryptography")

        self._rest_client = rest_client
        self._cert_dir = cert_dir
        self._subject = subject
        self._initial_cert_path = initial_cert_path
        self._initial_key_path = initial_key_path
        # Доля оставшегося срока действия сертификата, после которой начинаем
        # пробовать ротацию (0.5 — как только осталось меньше половины).
        self._rotation_threshold = rotation_threshold_fraction
        # Минимальный интервал между ПОПЫТКАМИ ротации (не путать с периодом
        # самой ротации) — не даёт долбить бэкенд/flash на каждой итерации
        # основного цикла, если сертификат уже "просрочен по порогу", но
        # обмен пока не удаётся.
        self._retry_interval_s = rotation_retry_interval_days * 86400
        self._clock = clock or time.time
        # Вызывается после КАЖДОГО успешного обмена (первичного или
        # ротации) — используется, например, чтобы пометить BackendClient
        # как online сразу же (он сам об этом не узнает, т.к. cert/get
        # выполняется через RestClient напрямую, минуя BackendClient).
        self._on_exchange_success = on_exchange_success
        self._rsa_key_size = rsa_key_size
        self._kms_url = kms_url.rstrip("/") if kms_url else None
        self._ca_bundle = ca_bundle
        # Обязательный query-параметр для KMS /bootstrap — идентификатор
        # точки доступа, для которой запрашивается первичный сертификат.
        self._access_point_id = access_point_id
        # WAF на KMS блокирует "ботовские" User-Agent — используем тот же
        # чёткий UA, что и RestClient для controller (бэкенд-команда должна
        # добавить его в allowlist WAF).
        self._user_agent = user_agent
        # Для тестов: подмена HTTP-сессии KMS-запроса.
        self._kms_session = kms_session

        os.makedirs(cert_dir, exist_ok=True)
        self._working_cert_path = os.path.join(cert_dir, "working_cert.pem")
        self._working_key_path = os.path.join(cert_dir, "working_key.pem")
        # Время последней ПОПЫТКИ ротации (не обязательно успешной) — для
        # троттлинга повторных попыток, см. _rotation_threshold/_retry_interval_s.
        # Живёт только в памяти процесса: переживать перезапуск ей не нужно —
        # после перезапуска контроллер просто попробует сразу же, это не
        # страшно (в отличие от лишней записи на flash при каждой попытке).
        self._last_rotation_attempt: Optional[float] = None

        # Если CA не задан в конфиге, но ранее был получен от KMS и сохранён на
        # диск — используем его для проверки controller-сервера.
        if self._ca_bundle is None:
            saved_ca_path = os.path.join(cert_dir, "ca.pem")
            if os.path.exists(saved_ca_path):
                self._ca_bundle = saved_ca_path
                self._rest_client.set_ca_bundle(saved_ca_path)

    # ------------------------------------------------------------------
    # Публичные операции
    # ------------------------------------------------------------------

    @property
    def has_working_certificate(self) -> bool:
        return os.path.exists(self._working_cert_path) and os.path.exists(self._working_key_path)

    def ensure_bootstrapped(self) -> None:
        """
        Убедиться, что у контроллера есть рабочий сертификат.

        Если рабочего сертификата ещё нет, но есть первичный — выполняет
        первичный обмен (п. 5.4.1, шаги 1-3).
        """
        if self.has_working_certificate:
            self._rest_client.set_client_cert(self._working_cert_path, self._working_key_path)
            return

        has_initial = bool(
            self._initial_cert_path and self._initial_key_path
            and os.path.exists(self._initial_cert_path)
            and os.path.exists(self._initial_key_path)
        )
        if not has_initial:
            if self._kms_url:
                logger.info("CertificateManager: нет первичного сертификата — запрашиваем у KMS (%s)", self._kms_url)
                has_initial = self._fetch_initial_from_kms()
            if not has_initial:
                logger.warning(
                    "CertificateManager: нет ни рабочего, ни первичного сертификата — "
                    "mTLS-соединение с бэкендом невозможно."
                )
                return

        logger.info("CertificateManager: первичный обмен сертификата...")
        self._rest_client.set_client_cert(self._initial_cert_path, self._initial_key_path)
        self._exchange_and_activate()
        self._delete_initial_certificate()

    def tick(self, now: float) -> None:
        """Совместимость с интерфейсом периодических сервисов (см. LGTUApplication)."""
        self.maybe_rotate(now)

    def maybe_rotate(self, now: Optional[float] = None) -> bool:
        """
        Проверить реальный остаток срока действия рабочего сертификата и,
        если он упал ниже порога (по умолчанию половина), попробовать
        ротацию (п. 5.4.1, шаг 4) — но не чаще, чем раз в
        ``rotation_retry_interval_days``, даже если предыдущая попытка
        провалилась. Пока обмен не удастся, попытки продолжаются с этим
        интервалом; после успеха новый сертификат снова "молодой", и до
        следующего пересечения порога ротация не запускается вовсе.

        Returns
        -------
        bool
            True, если ротация была выполнена.
        """
        if not self.has_working_certificate:
            return False

        now = now if now is not None else self._clock()

        try:
            valid_from, valid_until = self._read_working_cert_validity()
        except Exception:
            logger.exception("CertificateManager: не удалось прочитать срок действия рабочего сертификата")
            return False

        total_lifetime = valid_until - valid_from
        remaining = valid_until - now
        if total_lifetime <= 0 or remaining > total_lifetime * self._rotation_threshold:
            return False  # ещё не пора — остатка срока действия больше порога

        if self._last_rotation_attempt is not None and (now - self._last_rotation_attempt) < self._retry_interval_s:
            return False  # уже пробовали недавно, ждём следующего интервала

        logger.info(
            "CertificateManager: остаток срока действия сертификата %.1f%% (порог %.0f%%) — пробуем обновить",
            max(remaining, 0) / total_lifetime * 100, self._rotation_threshold * 100,
        )
        self._last_rotation_attempt = now
        try:
            # Важно: НЕ трогаем действующие working_cert/working_key файлы до
            # успешного ответа бэкенда — RestClient.call() ниже сам
            # аутентифицируется текущим (пока ещё валидным) рабочим
            # сертификатом по этим же путям. Если переименовать/удалить файл
            # заранее, сам запрос ротации сломается (путь для mTLS исчезнет).
            self._exchange_and_activate()
        except BackendApiError:
            logger.exception(
                "CertificateManager: ротация не удалась, остаёмся на старом сертификате "
                "(следующая попытка не раньше чем через %.0f ч.)", self._retry_interval_s / 3600,
            )
            return False

        return True

    # ------------------------------------------------------------------
    # Внутренние операции
    # ------------------------------------------------------------------

    def _exchange_and_activate(self) -> None:
        """Сгенерировать пару ключей+CSR, обменять на подписанный сертификат, активировать."""
        private_key_pem, csr_pem = self._generate_keypair_and_csr()

        # Запрос выполняется ДО какой-либо записи на working_cert/working_key —
        # если сейчас идёт ротация, аутентификация этого запроса использует
        # ещё действующий (старый) рабочий сертификат по тем же путям.
        response = self._rest_client.call("cert", "get", {"csr": csr_pem})
        crt_pem = response.get("crt")
        if not crt_pem:
            raise BackendApiError("cert/get: ответ не содержит поле 'crt'")

        # Пишем во временные файлы и атомарно заменяем ими действующие —
        # имя файла, на которое смотрит RestClient, остаётся тем же самым в
        # течение всей операции, поэтому сессия не может "потерять" сертификат.
        tmp_key_path = self._working_key_path + ".new"
        tmp_cert_path = self._working_cert_path + ".new"
        with open(tmp_key_path, "w", encoding="utf-8") as f:
            f.write(private_key_pem)
        os.chmod(tmp_key_path, 0o600)
        with open(tmp_cert_path, "w", encoding="utf-8") as f:
            f.write(crt_pem)

        os.replace(tmp_cert_path, self._working_cert_path)
        os.replace(tmp_key_path, self._working_key_path)

        # Новый сертификат снова "молодой" — забытая попытка ротации больше
        # не актуальна (следующая проверка порога всё равно её проигнорирует,
        # но чище явно сбросить).
        self._last_rotation_attempt = None
        self._rest_client.set_client_cert(self._working_cert_path, self._working_key_path)
        logger.info("CertificateManager: рабочий сертификат активирован")

        if self._on_exchange_success is not None:
            try:
                self._on_exchange_success()
            except Exception:
                logger.exception("CertificateManager: ошибка в on_exchange_success callback")

    def _generate_keypair_and_csr(self) -> tuple[str, str]:
        """Сгенерировать RSA-2048 ключ и CSR с Subject из конфигурации."""
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=self._rsa_key_size)

        name_attrs = [x509.NameAttribute(NameOID.ORGANIZATION_NAME, self._subject.organization)]
        for ou in self._subject.organizational_units:
            name_attrs.append(x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, ou))
        name_attrs.append(x509.NameAttribute(NameOID.COMMON_NAME, self._subject.common_name))

        csr = (
            x509.CertificateSigningRequestBuilder()
            .subject_name(x509.Name(name_attrs))
            .sign(private_key, hashes.SHA256())
        )

        private_key_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode("utf-8")
        csr_pem = csr.public_bytes(serialization.Encoding.PEM).decode("utf-8")
        return private_key_pem, csr_pem

    def _fetch_initial_from_kms(self) -> bool:
        """
        Запросить первичный сертификат у KMS-сервера (``GET /bootstrap``).

        Returns
        -------
        bool
            True, если сертификат успешно получен и сохранён на диск.
        """
        url = f"{self._kms_url}/bootstrap"
        params = {"access_point_id": self._access_point_id} if self._access_point_id is not None else None
        try:
            if self._kms_session is not None:
                session = self._kms_session
            elif _REQUESTS_AVAILABLE:
                session = _requests_lib.Session()
                if self._ca_bundle is not None:
                    session.verify = self._ca_bundle
            else:
                logger.error("CertificateManager: KMS bootstrap невозможен — модуль requests не установлен")
                return False

            response = session.get(
                url,
                params=params,
                headers={"Accept": "application/json", "User-Agent": self._user_agent},
                timeout=self._rest_client._timeout if hasattr(self._rest_client, "_timeout") else 10.0,
            )
            if response.status_code != 200:
                logger.error("CertificateManager: KMS bootstrap HTTP %s", response.status_code)
                return False

            data = response.json()
        except Exception:
            logger.exception("CertificateManager: ошибка при запросе к KMS bootstrap")
            return False

        # Реальный KMS отдаёт ответ в формате:
        # {"bootstrap": {"crt": ..., "private_key": ...}, "ca": {"crt": ...}}.
        # Поддерживаем и старый плоский формат {"cert": ..., "key": ...}.
        bootstrap = data.get("bootstrap") or data
        ca_data = data.get("ca") or {}
        cert_pem = bootstrap.get("crt") or data.get("cert")
        key_pem = bootstrap.get("private_key") or data.get("key")
        ca_pem = ca_data.get("crt")
        if not cert_pem or not key_pem:
            logger.error("CertificateManager: ответ KMS /bootstrap не содержит cert/key")
            return False

        # Определить пути для первичного сертификата (используем штатные пути
        # из конфига, или дефолтные в cert_dir).
        cert_path = self._initial_cert_path or os.path.join(self._cert_dir, "initial_cert.pem")
        key_path = self._initial_key_path or os.path.join(self._cert_dir, "initial_key.pem")

        with open(cert_path, "w", encoding="utf-8") as f:
            f.write(cert_pem)
        with open(key_path, "w", encoding="utf-8") as f:
            f.write(key_pem)
        os.chmod(key_path, 0o600)

        self._initial_cert_path = cert_path
        self._initial_key_path = key_path

        # Сохраняем CA, выданный KMS, и используем его для проверки controller-сервера,
        # если в конфиге не задан собственный ca_bundle.
        if ca_pem:
            ca_path = os.path.join(self._cert_dir, "ca.pem")
            with open(ca_path, "w", encoding="utf-8") as f:
                f.write(ca_pem)
            if self._ca_bundle is None:
                self._ca_bundle = ca_path
                self._rest_client.set_ca_bundle(ca_path)
                logger.info("CertificateManager: CA от KMS сохранён и установлен для RestClient")

        logger.info("CertificateManager: первичный сертификат получен от KMS и сохранён")
        return True

    def _delete_initial_certificate(self) -> None:
        for path in (self._initial_cert_path, self._initial_key_path):
            if path and os.path.exists(path):
                os.remove(path)
        logger.info("CertificateManager: первичный сертификат удалён с контроллера")

    def _read_working_cert_validity(self) -> tuple[float, float]:
        """Прочитать реальный ``notBefore``/``notAfter`` рабочего сертификата (epoch, UTC)."""
        with open(self._working_cert_path, "rb") as f:
            cert = x509.load_pem_x509_certificate(f.read())
        not_before = getattr(cert, "not_valid_before_utc", None)
        not_after = getattr(cert, "not_valid_after_utc", None)
        if not_before is None:  # cryptography < 42: только наивные UTC-датумы
            not_before = cert.not_valid_before.replace(tzinfo=timezone.utc)
        if not_after is None:
            not_after = cert.not_valid_after.replace(tzinfo=timezone.utc)
        return not_before.timestamp(), not_after.timestamp()
