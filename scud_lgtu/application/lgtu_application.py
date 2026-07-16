"""LGTU application - основная логика приложения."""
import asyncio
import logging
import queue
import threading
import time
from typing import Optional
from scud_lgtu.infrastructure.engine import ScudEngine
from scud_lgtu.infrastructure.persistence.event_store import EventStore, PassageEvent, EventType, EventSource
from scud_lgtu.infrastructure.cache.access_cache import LocalAccessCache
from scud_lgtu.infrastructure.backend.client import BackendClient
from scud_lgtu.infrastructure.sound.player import SoundPlayer
from scud_lgtu.domain.turnstile import TurnstileState
from scud_lgtu.domain.services import AccessPolicy, PassageTracker
from scud_lgtu.domain.events import QrRead, CardRead, MuxInputChanged
from scud_lgtu.domain.models import Credential, Passage
from scud_lgtu.domain.enums import TokenTypeEnum, DirectionEnum, ResultEnum
from scud_lgtu.application.event_bus import EventBus
from scud_lgtu.application.services.access_service import AccessService
from scud_lgtu.application.services.passage_service import PassageService
from scud_lgtu.application.services.sync_service import SyncService
from scud_lgtu.application.handlers.qr import handle_qr_read
from scud_lgtu.application.handlers.card import handle_card_read
from scud_lgtu.application.handlers.alarm import handle_alarm_changed
from scud_lgtu.application.handlers.button import handle_button_pressed
from scud_lgtu.application.handlers.mux import handle_mux_input_changed

logger = logging.getLogger(__name__)


class LGTUApplication:
    """Main LGTU application implementing clean architecture."""
    
    def __init__(
        self,
        engine: ScudEngine,
        cache: LocalAccessCache,
        store: EventStore,
        backend: BackendClient,
        config: dict
    ):
        """Initialize LGTU application."""
        self._engine = engine
        self._config = config
        self._running = False
        
        # Domain components
        timings = config.get("timings", {})
        auth_timeout = timings.get("auth_timeout_s", 30.0)
        self._turnstile = TurnstileState(auth_timeout=auth_timeout)
        self._access_policy = AccessPolicy(cache=cache)
        self._passage_tracker = PassageTracker()
        
        # Infrastructure adapters
        self._sound_player = SoundPlayer()
        
        # Application services
        self._event_bus = EventBus()
        self._access_service = AccessService(cache)
        self._passage_service = PassageService(store)
        self._sync_service = SyncService(backend, store, sync_interval=timings.get("backend_sync_interval_s", 60.0))
        
        # Event loop for async operations
        self._loop = None
        self._loop_thread = None
        
        # Register handlers
        self._register_handlers()
    
    def _register_handlers(self) -> None:
        """Register event handlers."""
        # Register domain event handlers
        self._event_bus.subscribe("QrRead", lambda e: handle_qr_read(
            e, self._turnstile, self._access_policy, self._passage_tracker
        ))
        self._event_bus.subscribe("CardRead", lambda e: handle_card_read(
            e, self._turnstile, self._access_policy, self._passage_tracker
        ))
        self._event_bus.subscribe("AlarmChanged", lambda e: handle_alarm_changed(e, self._turnstile))
        self._event_bus.subscribe("ButtonPressed", lambda e: handle_button_pressed(e, self._turnstile))
        self._event_bus.subscribe("MuxInputChanged", lambda e: handle_mux_input_changed(e, self._event_bus))
    
    def _start_event_loop(self) -> None:
        """Start asyncio event loop in separate thread."""
        def run_loop():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            self._event_bus.set_event_loop(self._loop)
            self._loop.run_forever()
        
        self._loop_thread = threading.Thread(target=run_loop, daemon=True)
        self._loop_thread.start()
    
    def _stop_event_loop(self) -> None:
        """Stop asyncio event loop."""
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._loop_thread and self._loop_thread.is_alive():
            self._loop_thread.join(timeout=2.0)
    
    def _convert_scud_event_to_domain(self, scud_event) -> Optional:
        """Convert ScudEvent to domain event."""
        from scud_lgtu.infrastructure.persistence.event_store import EventType, EventSource
        
        logger.debug(f"Converting ScudEvent: type={scud_event.type}, source={scud_event.source}, payload={scud_event.payload}")
        
        if scud_event.type == EventType.QR_READ:
            credential = Credential(
                token_type=TokenTypeEnum.MAXID,
                value=str(scud_event.payload.get("max_id", "")),
                encrypted=False
            )
            event = QrRead(
                credential=credential,
                reader_id=scud_event.payload.get("reader", "unknown")
            )
            logger.info(f"QR Read event: {event}")
            return event
        elif scud_event.type == EventType.CARD_READ:
            credential = Credential(
                token_type=TokenTypeEnum.CARDID,
                value=str(scud_event.payload.get("card_data", "")),
                encrypted=scud_event.payload.get("encrypted", False)
            )
            event = CardRead(
                credential=credential,
                reader_id="wiegand"
            )
            logger.info(f"Card Read event: {event}")
            return event
        elif scud_event.type == EventType.MUX_CHANGED:
            # Обработка изменений мультиплексора - payload содержит словарь states
            states = scud_event.payload.get("states", {})
            for input_name, state in states.items():
                event = MuxInputChanged(
                    input_name=input_name,
                    state=state == 0  # 0 = активный (low active)
                )
                logger.info(f"Mux Input Changed event: {event}")
                return event
        elif scud_event.type == EventType.SERIAL_DATA:
            # Обработка данных из serial порта (QR-код)
            data = scud_event.payload.get("data", "")
            if data:
                credential = Credential(
                    token_type=TokenTypeEnum.MAXID,
                    value=str(data),
                    encrypted=False
                )
                event = QrRead(
                    credential=credential,
                    reader_id=scud_event.payload.get("port", "serial")
                )
                logger.info(f"Serial QR Read event: {event}")
                return event
        
        logger.debug(f"Unknown event type: {scud_event.type}")
        return None
    
    def run(self) -> None:
        """Run the main application loop."""
        logger.info("LGTUApplication: starting")
        self._running = True
        
        # Start event loop for async operations
        self._start_event_loop()
        
        # Get event queue from engine
        event_queue = self._engine.get_event_queue()
        
        try:
            while self._running:
                # Process events from engine
                try:
                    scud_event = event_queue.get(timeout=0.1)
                    logger.debug(f"Received ScudEvent from engine: {scud_event}")
                    domain_event = self._convert_scud_event_to_domain(scud_event)
                    
                    if domain_event:
                        self._event_bus.publish(domain_event)
                except queue.Empty:
                    # Нормальное поведение - очередь пуста
                    pass
                except Exception as e:
                    logger.error(f"Error processing event: {e}")
                
                # Tick turnstile state machine
                now = time.time()
                commands = self._turnstile.tick(now)
                # Apply commands (to be implemented with actuator)
                
                # Tick sync service
                self._sync_service.tick(now)
                
        except KeyboardInterrupt:
            logger.info("LGTUApplication: interrupted")
        finally:
            self.stop()
    
    def stop(self) -> None:
        """Stop the application."""
        logger.info("LGTUApplication: stopping")
        self._running = False
        self._stop_event_loop()
        logger.info("LGTUApplication: stopped")
