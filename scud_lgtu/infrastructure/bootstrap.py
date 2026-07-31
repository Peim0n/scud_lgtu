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
from typing import Any
import os
import logging
from scud_lgtu.infrastructure.cache.access_cache import LocalAccessCache
from scud_lgtu.infrastructure.cache.repository import AccessRepositoryAdapter
from scud_lgtu.infrastructure.persistence.event_log import EventLogAdapter
from scud_lgtu.infrastructure.persistence.event_store import EventStore
from scud_lgtu.infrastructure.backend.gateway import BackendGatewayAdapter
from scud_lgtu.infrastructure.backend.client import BackendClient
from scud_lgtu.infrastructure.sound.output import SoundOutputAdapter
from scud_lgtu.infrastructure.sound.player import SoundPlayer
from scud_lgtu.infrastructure.firmware.gpio.actuator import ShiftRegisterActuator
from scud_lgtu.infrastructure.engine import ScudEngine
from scud_lgtu.infrastructure.config.module_resolver import ModuleResolver
from scud_lgtu.infrastructure.config import load
from scud_lgtu.infrastructure.firmware.serial.qr_decoder import QRDecoder
from scud_lgtu.infrastructure.devices.turnstile.turnstile_device import TurnstileDevice
from scud_lgtu.domain.access import AccessPolicy, PassageTracker
from scud_lgtu.application.lgtu_application import LGTUApplication
from scud_lgtu.application.services.passage_service import PassageService
from scud_lgtu.application.services.sync_service import SyncService


def build_application(config_path: str = None) -> LGTUApplication:
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
    # Загрузить конфигурацию
    if config_path is None:
        script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        config_path = os.path.join(script_dir, "config.yml")

    config = load(config_path)

    # Настройка логирования из конфига
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

    # Загрузить тайминги (нужно до создания ScudEngine)
    timings = config.get("timings", {})

    # Загрузить маппинг устройств
    devices = config.get("devices", {})

    # Добавить зоны прохода к устройствам для обработчика проходов
    passage_zones = config.get("passage", {}).get("zones", [])
    devices["passage_zones"] = passage_zones

    # Путь к кэшу для компонента кэша доступа
    cache_path = os.path.join(os.path.dirname(config_path), "infrastructure", "cache", "local_access.json")

    # Создать программные компоненты напрямую
    if config.get("mode") == "mock":
        from scud_lgtu.tests.mocks.mock_engine import MockEngine
        engine = MockEngine(config=config, timings=timings)
    else:
        engine = ScudEngine(config=config, timings=timings)
    cache = LocalAccessCache(path=cache_path)
    store = EventStore()
    backend = BackendClient(base_url=config["backend"]["base_url"])
    sound_player = SoundPlayer(
        sound_dir=config["sound"]["sound_dir"],
        player_cmd=config["sound"]["player_cmd"],
        sound_queue_maxsize=timings["sound_queue_maxsize"],
    )

    # Опциональный QR-декодер
    qr_decoder = None
    qr_dir = config.get("qr_decoder", {}).get("keys_dir", "infrastructure/keys")
    keys_dir = os.path.join(os.path.dirname(config_path), qr_dir)
    try:
        qr_decoder = QRDecoder(keys_dir=keys_dir)
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

    # Доменные компоненты
    auth_timeout = resolver.get_timing("business", "auth_timeout_s")

    device_logic = TurnstileDevice(auth_timeout=auth_timeout, timings=timings, resolver=resolver)
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
    )

    return application
