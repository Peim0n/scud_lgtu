"""
Bootstrap - контейнер внедрения зависимостей системы СКУД.

Этот модуль реализует функцию сборки приложения LGTU со всеми зависимостями.
Функция загружает конфигурацию, создаёт инфраструктурные компоненты (ScudEngine, кэш, хранилище),
доменные компоненты (TurnstileDevice, AccessPolicy, PassageTracker) и сервисы приложения,
затем связывает их в готовое к работе приложение.

Функции
-------
- build_application: собрать приложение LGTU со всеми зависимостями
"""
import logging
import os
from typing import Any

from app.application.lgtu_application import LGTUApplication
from app.application.services.accesspoint_inventory_service import (
    AccesspointInventoryService,
)
from app.application.services.key_sync_service import KeySyncService
from app.application.services.passage_service import PassageService
from app.application.services.sync_service import SyncService
from app.domain.access import AccessPolicy, PassageTracker
from app.infrastructure.backend.certificate_manager import (
    CertificateManager,
    CertificateSubject,
)
from app.infrastructure.backend.client import BackendClient
from app.infrastructure.backend.gateway import BackendGatewayAdapter
from app.infrastructure.backend.rest_client import DEFAULT_USER_AGENT, RestClient
from app.infrastructure.cache.access_cache import LocalAccessCache
from app.infrastructure.cache.repository import AccessRepositoryAdapter
from app.infrastructure.config import load
from app.infrastructure.config.module_resolver import ModuleResolver
from app.infrastructure.devices.device_factory import create_device
from app.infrastructure.engine import ScudEngine
from app.infrastructure.firmware.gpio.actuator import ShiftRegisterActuator
from app.infrastructure.firmware.serial.qr_decoder import QRDecoder
from app.infrastructure.persistence.event_log import EventLogAdapter
from app.infrastructure.persistence.event_store import EventStore
from app.infrastructure.sound.output import SoundOutputAdapter
from app.infrastructure.sound.player import SoundPlayer

logger = logging.getLogger(__name__)


def _resolve_config_path(config_path: str | None) -> str:
    if config_path is not None:
        return config_path
    script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(script_dir, "config.yml")


def _configure_logging(config: dict) -> None:
    """Настройка логирования из конфига — общая для build_application и build_backend_client."""
    logging_config = config.get("logging", {})
    log_level = logging_config.get("level", "INFO")
    log_format = logging_config.get("format", "%(asctime)s %(name)s [%(levelname)s] %(message)s")
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format=log_format,
    )

    # Детальная настройка по модулям
    loggers_config = logging_config.get("loggers", {})
    for logger_name, logger_level in loggers_config.items():
        logger = logging.getLogger(logger_name)
        logger.setLevel(getattr(logging, logger_level.upper()))


def build_backend_client(
    config_path: str | None = None, ensure_bootstrap: bool = True,
) -> tuple[BackendClient, Any]:
    """
    Собрать только backend-часть (RestClient/BackendClient/CertificateManager)
    без остального приложения (ScudEngine и GPIO).

    Нужна для CLI-утилиты управления сертификатом (``manage.py``) и в
    перспективе для веб-интерфейса администрирования — им нельзя дёргать
    ``build_application()``, т.к. это поднимет GPIO/ScudEngine и приведёт к
    конфликту с уже запущенным основным процессом контроллера (единственным
    владельцем GPIO-пинов).

    Parameters
    ----------
    config_path : str, optional
        Путь к файлу конфигурации.
    ensure_bootstrap : bool
        Выполнить ``CertificateManager.ensure_bootstrapped()`` сразу после
        сборки (как это всегда делает ``build_application()``). Для команд
        вроде ``cert status`` это не нужно — False, чтобы не дёргать
        KMS/бэкенд лишний раз.

    Returns
    -------
    tuple[BackendClient, CertificateManager | None]
    """
    config_path = _resolve_config_path(config_path)
    config = load(config_path)
    _configure_logging(config)
    base_dir = os.path.dirname(config_path)
    return _build_backend_client(config, base_dir, ensure_bootstrap=ensure_bootstrap)


def build_application(config_path: str | None = None) -> LGTUApplication:
    """
    Собрать приложение LGTU со всеми зависимостями.

    Parameters
    ----------
    config_path : str, optional
        Путь к файлу конфигурации

    Returns
    -------
    LGTUApplication
        Сконфигурированное приложение
    """
    config_path = _resolve_config_path(config_path)
    config = load(config_path)
    _configure_logging(config)

    # Загрузить тайминги (нужно до создания ScudEngine)
    timings = config.get("timings", {})

    # Загрузить маппинг устройств
    devices = config.get("devices", {})

    # Добавить зоны прохода к устройствам для обработчика проходов
    passage_zones = config.get("passage", {}).get("zones", [])
    devices["passage_zones"] = passage_zones

    base_dir = os.path.dirname(config_path)

    # Создать программные компоненты напрямую
    engine: Any
    if config.get("mode") == "mock":
        from app.tests.mocks.mock_engine import MockEngine
        engine = MockEngine(config=config, timings=timings)
    else:
        engine = ScudEngine(config=config, timings=timings)
    access_cfg = config.get("access", {})
    cache = LocalAccessCache(
        static_key=access_cfg.get("static_key"),
        dynamic_key=access_cfg.get("dynamic_key"),
    )
    store = EventStore()
    backend, cert_manager = _build_backend_client(config, base_dir)
    sound_cfg = config.get("sound", {})
    sound_player = SoundPlayer(
        sound_dir=sound_cfg["sound_dir"],
        player_cmd=sound_cfg["player_cmd"],
        sound_queue_maxsize=timings["sound_queue_maxsize"],
        stop_timeout=float(sound_cfg.get("stop_timeout_s", 5.0)),
        play_timeout=float(sound_cfg.get("play_timeout_s", 10.0)),
    )

    # Опциональный QR-декодер (ключи загружаются в память через KeySyncService)
    qr_decoder = None
    qr_base_url = config.get("qr_decoder", {}).get("base_url", "https://pass.lipetsk.ru/?")
    try:
        qr_decoder = QRDecoder(qr_base_url=qr_base_url)
    except ImportError:
        logger.warning("QR decoder не инициализирован. QR коды не будут декодироваться.")

    # Создать адаптеры
    access_repository = AccessRepositoryAdapter(cache)
    event_log = EventLogAdapter(store)
    sound_output = SoundOutputAdapter(sound_player)
    backend_gateway = BackendGatewayAdapter(backend)

    # Адаптер актуатора
    actuator = ShiftRegisterActuator(engine)

    # Инициализация ModuleResolver для новой архитектуры
    # ModuleResolver реализует интерфейс ConfigResolver из domain слоя
    resolver: Any = ModuleResolver(config)

    device_logic = create_device(config, timings=timings, resolver=resolver)
    access_policy = AccessPolicy(repository=access_repository)
    passage_tracker = PassageTracker()

    # Сервисы приложения
    passage_service = PassageService(event_log, passage_tracker=passage_tracker)
    sync_service = SyncService(
        backend_gateway,
        event_log,
        access_repository,
        sync_interval=float(timings["backend_sync_interval_s"]),
    )

    # Периодические сервисы синхронизации с бэкендом (§5.4)
    periodic_services: list = []
    if cert_manager is not None:
        periodic_services.append(cert_manager)
    key_sync_service = KeySyncService(
        backend_gateway,
        qr_decoder=qr_decoder,
        sync_interval_s=float(timings.get("key_sync_interval_s", 86400)),
    )
    periodic_services.append(key_sync_service)
    accesspoint_service = AccesspointInventoryService(
        backend_gateway,
        interface=config.get("backend", {}).get("network_interface"),
        sync_interval_s=float(timings.get("accesspoint_sync_interval_s", 86400)),
    )
    periodic_services.append(accesspoint_service)

    # Создать приложение
    application = LGTUApplication(
        event_source=engine,
        device_logic=device_logic,
        access_policy=access_policy,
        passage_tracker=passage_tracker,
        passage_service=passage_service,
        sync_service=sync_service,
        actuator=actuator,
        sound_output=sound_output,
        config=config,
        devices=devices,
        qr_decoder=qr_decoder,
        periodic_services=periodic_services,
    )

    return application


def _build_backend_client(
    config: dict, base_dir: str, ensure_bootstrap: bool = True,
) -> tuple[BackendClient, Any]:
    """
    Собрать ``BackendClient`` с mTLS-транспортом и (при наличии сертификатов)
    ``CertificateManager`` для первичного обмена/ротации (§5.4.1).

    Parameters
    ----------
    ensure_bootstrap : bool
        Вызвать ``CertificateManager.ensure_bootstrapped()`` сразу после
        создания. False — для случаев, когда лишний сетевой запрос не нужен
        (например, CLI-команда ``cert status``).

    Returns
    -------
    tuple[BackendClient, CertificateManager | None]
        Клиент и менеджер сертификатов (None, если модуль cryptography
        недоступен или сертификаты не настроены — тогда BackendClient
        работает без клиентского сертификата и запросы будут отклонены
        бэкендом по mTLS).
    """
    backend_cfg = config.get("backend", {})
    base_url = backend_cfg["base_url"]
    ca_bundle = backend_cfg.get("ca_bundle")
    timeout = float(backend_cfg.get("request_timeout_s", 10.0))
    api_path_prefix = backend_cfg.get("api_path_prefix", "/controller/v1")
    tcp_keepalive_time = int(backend_cfg.get("tcp_keepalive_time_s", 300))
    tcp_keepalive_probes = int(backend_cfg.get("tcp_keepalive_probes", 3))
    tcp_keepalive_intvl = int(backend_cfg.get("tcp_keepalive_intvl_s", 20))
    verify_hostname = backend_cfg.get("verify_hostname", True)
    user_agent = backend_cfg.get("user_agent", DEFAULT_USER_AGENT)

    rest_client = RestClient(
        base_url,
        ca_bundle=ca_bundle,
        timeout=timeout,
        api_path_prefix=api_path_prefix,
        tcp_keepalive_time=tcp_keepalive_time,
        tcp_keepalive_probes=tcp_keepalive_probes,
        tcp_keepalive_intvl=tcp_keepalive_intvl,
        verify_hostname=verify_hostname,
        user_agent=user_agent,
    )
    backend = BackendClient(rest_client=rest_client)

    cert_cfg = backend_cfg.get("cert")
    cert_manager = None
    if cert_cfg:
        subject_cfg = cert_cfg.get("subject", {})
        subject = CertificateSubject(
            organization=subject_cfg.get("organization", ""),
            organizational_units=subject_cfg.get("organizational_units", []),
            common_name=subject_cfg.get("common_name", ""),
        )
        # Сертификаты хранятся в /etc/scud_lgtu/certs/ на проде (read-write),
        # в dev — рядом с config.yml.
        runtime_dir = "/etc/scud_lgtu"
        if os.path.isdir(runtime_dir):
            cert_dir = os.path.join(runtime_dir, "certs")
        else:
            cert_dir = os.path.join(base_dir, cert_cfg.get("cert_dir", "infrastructure/certs"))
        initial_cert_path = cert_cfg.get("initial_cert_path")
        initial_key_path = cert_cfg.get("initial_key_path")
        if initial_cert_path:
            initial_cert_path = os.path.join(base_dir, initial_cert_path)
        if initial_key_path:
            initial_key_path = os.path.join(base_dir, initial_key_path)

        kms_url = backend_cfg.get("kms_url")
        access_point_id = backend_cfg.get("access_point_id")

        try:
            cert_manager = CertificateManager(
                rest_client,
                cert_dir=cert_dir,
                subject=subject,
                initial_cert_path=initial_cert_path,
                initial_key_path=initial_key_path,
                rotation_threshold_fraction=float(cert_cfg.get("rotation_threshold_fraction", 0.5)),
                rotation_retry_interval_days=float(cert_cfg.get("rotation_retry_interval_days", 1)),
                on_exchange_success=backend.mark_online,
                rsa_key_size=int(cert_cfg.get("rsa_key_size", 2048)),
                kms_url=kms_url,
                ca_bundle=ca_bundle,
                access_point_id=access_point_id,
                user_agent=user_agent,
            )
            if ensure_bootstrap:
                cert_manager.ensure_bootstrapped()
        except ImportError:
            logger.warning("CertificateManager не инициализирован: модуль cryptography не установлен.")
            cert_manager = None
        except Exception:
            logger.exception("CertificateManager: не удалось выполнить первичный обмен сертификата")

    return backend, cert_manager
