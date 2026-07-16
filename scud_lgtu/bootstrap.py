"""Bootstrap - контейнер внедрения зависимостей."""
import os
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
    """Build LGTU application with all dependencies."""
    # Load configuration
    if config_path is None:
        script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        config_path = os.path.join(script_dir, "config.yml")
    
    config = load_config(config_path)
    
    # Create infrastructure components
    engine = ScudEngine(config)
    
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
    timings = config.get("timings", {})
    auth_timeout = timings.get("auth_timeout_s", 5.0)
    turnstile = TurnstileState(auth_timeout=auth_timeout, timings=timings)
    access_policy = AccessPolicy(cache=cache)
    passage_tracker = PassageTracker()
    
    # Application services
    event_bus = EventBus()
    access_service = AccessService(cache)
    passage_service = PassageService(store)
    sync_service = SyncService(backend, store, sync_interval=timings.get("backend_sync_interval_s", 60.0))
    
    # Create application
    application = LGTUApplication(
        engine=engine,
        cache=cache,
        store=store,
        backend=backend,
        config=config
    )
    
    return application
