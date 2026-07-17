"""
Bootstrap - контейнер внедрения зависимостей системы СКУД.

Этот модуль реализует функцию сборки приложения LGTU со всеми зависимостями.
Функция загружает конфигурацию, создаёт инфраструктурные компоненты (ScudEngine, кэш, хранилище),
доменные компоненты (TurnstileState, AccessPolicy, PassageTracker) и сервисы приложения,
затем связывает их в готовое к работе приложение.

Функции
-------
- build_application: собрать приложение LGTU со всеми зависимостями
"""
import os
import logging
from scud_lgtu.infrastructure.engine import ScudEngine
from scud_lgtu.infrastructure.cache.access_cache import LocalAccessCache
from scud_lgtu.infrastructure.persistence.event_store import EventStore
from scud_lgtu.infrastructure.backend.client import BackendClient
from scud_lgtu.infrastructure.sound.player import SoundPlayer
from scud_lgtu.infrastructure.cache.repository import AccessRepositoryAdapter
from scud_lgtu.infrastructure.persistence.event_log import EventLogAdapter
from scud_lgtu.infrastructure.sound import SoundOutputAdapter
from scud_lgtu.infrastructure.backend import BackendGatewayAdapter
from scud_lgtu.infrastructure.gpio.actuator import ShiftRegisterActuator
from scud_lgtu.infrastructure.gpio.pin_map import load_pin_map
from scud_lgtu.domain.turnstile import TurnstileState
from scud_lgtu.domain.services import AccessPolicy, PassageTracker
from scud_lgtu.application.lgtu_application import LGTUApplication
from scud_lgtu.application.services.access_service import AccessService
from scud_lgtu.application.services.passage_service import PassageService
from scud_lgtu.application.services.sync_service import SyncService
from scud_lgtu.application.event_bus import EventBus
from scud_lgtu.config import load as load_config


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
    # Load configuration
    if config_path is None:
        script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        config_path = os.path.join(script_dir, "config.yml")

    config = load_config(config_path)

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

    # Load timings (нужно до создания ScudEngine)
    timings = config.get("timings", {})

    # Load device mapping
    devices = config.get("devices", {})

    # Add passage zones to devices for passage handler
    passage_zones = config.get("passage", {}).get("zones", [])
    devices["passage_zones"] = passage_zones

    # Create infrastructure components
    engine = ScudEngine(config, timings=timings)

    # Cache
    cache_path = os.path.join(os.path.dirname(config_path), "local_access.json")
    cache = LocalAccessCache(path=cache_path)

    # Event store
    store = EventStore()

    # Backend
    backend = BackendClient()

    # Sound player
    sound_player = SoundPlayer(timings=timings)

    # Create adapters
    access_repository = AccessRepositoryAdapter(cache)
    event_log = EventLogAdapter(store)
    sound_output = SoundOutputAdapter(sound_player)
    backend_gateway = BackendGatewayAdapter(backend)

    # Pin mapping
    pin_map = load_pin_map(config)
    actuator = ShiftRegisterActuator(engine, pin_map)

    # Domain components
    auth_timeout = timings.get("auth_timeout_s", 5.0)  # Время действия авторизации из конфига
    passage_devices = devices.get("passage", {})
    turnstile = TurnstileState(auth_timeout=auth_timeout, timings=timings, devices=passage_devices)
    access_policy = AccessPolicy(cache=cache)
    passage_tracker = PassageTracker()

    # Application services
    event_bus = EventBus(turnstile=turnstile)
    access_service = AccessService(cache)
    passage_service = PassageService(store)
    sync_service = SyncService(backend, store, sync_interval=timings.get("backend_sync_interval_s", 60.0))

    # Create application
    application = LGTUApplication(
        engine=engine,
        cache=cache,
        store=store,
        backend=backend,
        config=config,
        devices=devices  # Передаем мапинг устройств
    )

    return application
