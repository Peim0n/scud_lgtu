"""
Основное приложение LGTU системы СКУД.

Этот модуль реализует основную логику приложения, связывающую инфраструктуру (ScudEngine)
с доменной логикой (TurnstileState, AccessPolicy, PassageTracker) и обработчиками событий.
Приложение подписывается на события от ScudEngine, преобразует их в доменные события
и публикует их в EventBus для обработки соответствующими обработчиками.

Классы
-------
- LGTUApplication: основное приложение, реализующее чистую архитектуру

Методы LGTUApplication
----------------------
- __init__: инициализировать приложение с движком, кэшем, хранилищем и конфигурацией
- run: запустить главный цикл приложения
- stop: остановить приложение
- _handle_output_commands: обработать событие с командами для выхода
- _convert_scud_event_to_domain: преобразовать событие ScudEngine в доменное событие
- _initialize_button_states: инициализировать состояния кнопок для предотвращения ложных срабатываний
- _initialize_outputs: инициализировать все выходы в безопасное состояние (реле закрыты)
- _start_event_loop: запустить asyncio event loop в отдельном потоке
"""
import asyncio
import logging
import queue
import threading
import time
from typing import Optional
from scud_lgtu.infrastructure.engine import ScudEngine
from scud_lgtu.infrastructure.serial.qr_codec import QRDecoder
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
from scud_lgtu.application.handlers.passage import handle_passage_detected
from scud_lgtu.application.handlers.mux import handle_mux_input_changed
from scud_lgtu.application.handlers.alarm import handle_alarm_changed
from scud_lgtu.application.handlers.button import handle_button_pressed

logger = logging.getLogger(__name__)


class LGTUApplication:
    """Основное приложение LGTU, реализующее чистую архитектуру."""

    def __init__(
        self,
        engine: ScudEngine,
        cache: LocalAccessCache,
        store: EventStore,
        backend: BackendClient,
        config: dict,
        devices: dict = None
    ):
        """
        Инициализировать приложение LGTU.

        Parameters
        ----------
        engine : ScudEngine
            Движок для управления оборудованием
        cache : LocalAccessCache
            Кэш доступа
        store : EventStore
            Хранилище событий
        backend : BackendClient
            Клиент бэкенда
        config : dict
            Конфигурация
        devices : dict, optional
            Мапинг устройств из конфига
        """
        self._engine = engine
        self._config = config
        self._devices = devices or {}
        self._running = False

        # QR decoder (опционально, если установлен cryptography)
        self._qr_decoder = None
        try:
            keys_dir = config.get("qr_keys_dir", "scud_lgtu/key")
            self._qr_decoder = QRDecoder(keys_dir=keys_dir)
            logger.info("QR decoder инициализирован")
        except ImportError as e:
            logger.warning(f"QR decoder не инициализирован: {e}. QR коды не будут декодироваться.")

        # Domain components
        timings = config.get("timings", {})
        auth_timeout = timings.get("auth_timeout_s", 5.0)
        passage_devices = devices.get("passage", {})
        self._turnstile = TurnstileState(auth_timeout=auth_timeout, timings=timings, devices=passage_devices)
        self._access_policy = AccessPolicy(cache=cache)
        self._passage_tracker = PassageTracker()

        # Infrastructure adapters
        self._sound_player = SoundPlayer()

        # Application services
        self._event_bus = EventBus(turnstile=self._turnstile)
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
            e, self._turnstile, self._access_policy, self._passage_tracker, self._event_bus, self._devices
        ))
        self._event_bus.subscribe("CardRead", lambda e: handle_card_read(
            e, self._turnstile, self._access_policy, self._passage_tracker, self._event_bus, self._devices
        ))
        self._event_bus.subscribe("PassageDetected", lambda e: handle_passage_detected(
            e, self._turnstile, self._passage_tracker, self._event_bus, self._passage_service, self._devices
        ))
        self._event_bus.subscribe("MuxInputChanged", lambda e: handle_mux_input_changed(e, self._event_bus))
        self._event_bus.subscribe("AlarmChanged", lambda e: handle_alarm_changed(e, self._turnstile, self._event_bus))
        self._event_bus.subscribe("ButtonPressed", lambda e: handle_button_pressed(e, self._turnstile, self._event_bus, self._devices))
        self._event_bus.subscribe("OutputCommandsGenerated", lambda e: self._handle_output_commands(e))
    
    def _handle_output_commands(self, event) -> None:
        """Обработать событие с командами для выхода."""
        from scud_lgtu.domain.events import OutputCommandsGenerated
        if isinstance(event, OutputCommandsGenerated):
            # Собираем все команды в словарь состояний для сдвигового регистра
            output_states = {}
            for cmd in event.commands:
                output_states[cmd.name] = cmd.state

            # Отправляем состояния в сдвиговый регистр через публичный интерфейс engine
            if output_states:
                try:
                    self._engine.set_output_mask(output_states)
                except Exception as e:
                    logger.error(f"Error sending to shift register: {e}")
    
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
    
    def _get_reader_id(self, reader: str) -> str:
        """Получить reader_id из мапинга reader_names."""
        reader_names = self._devices.get("reader_names", {})
        return reader_names.get(reader, reader)

    def _decode_qr_credential(self, data: str) -> Optional[Credential]:
        """Декодировать QR код в Credential."""
        if self._qr_decoder is not None:
            try:
                qr_fields = self._qr_decoder.decode_url(data)
                max_id = qr_fields.get("max_id")
                if max_id is None:
                    logger.error(f"QR код не содержит max_id: {data}")
                    return None

                return Credential(
                    token_type=TokenTypeEnum.MAXID,
                    value=str(max_id),
                    encrypted=False
                )
            except Exception as e:
                logger.error(f"Ошибка декодирования QR кода: {e}")
                return None
        else:
            # Если decoder недоступен, используем URL как есть
            logger.warning("QR decoder недоступен, используется URL как credential value")
            return Credential(
                token_type=TokenTypeEnum.MAXID,
                value=str(data),
                encrypted=False
            )

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
            reader = scud_event.payload.get("reader", "unknown")
            reader_id = self._get_reader_id(reader)
            event = QrRead(
                credential=credential,
                reader_id=reader_id
            )
            logger.info(f"QR Read event: {event}")
            return event
        elif scud_event.type == EventType.CARD_READ:
            credential = Credential(
                token_type=TokenTypeEnum.CARDID,
                value=str(scud_event.payload.get("card_data", "")),
                encrypted=scud_event.payload.get("encrypted", False)
            )
            reader = scud_event.payload.get("reader", "unknown")
            reader_id = self._get_reader_id(reader)
            event = CardRead(
                credential=credential,
                reader_id=reader_id
            )
            logger.info(f"Card Read event: {event}")
            return event
        elif scud_event.type == EventType.MUX_CHANGED:
            # Обработка изменений мультиплексора - payload содержит словарь states
            states = scud_event.payload.get("states", {})
            events = []
            for input_name, state in states.items():
                # Кнопки - low active (0 = нажатие), alarm - high active (1 = тревога)
                if input_name == "alarm":
                    state_bool = state == 1  # 1 = тревога
                else:
                    state_bool = state == 0  # 0 = активный для кнопок и сенсоров
                event = MuxInputChanged(
                    input_name=input_name,
                    state=state_bool
                )
                logger.debug(f"Mux Input Changed event: {event}")
                events.append(event)
            return events if events else None
        elif scud_event.type == EventType.SERIAL_DATA:
            # Обработка данных из serial порта (QR-код)
            data = scud_event.payload.get("data", "")
            if data:
                credential = self._decode_qr_credential(data)
                if credential is None:
                    return None

                reader = scud_event.payload.get("reader", "unknown")
                reader_id = self._get_reader_id(reader)
                event = QrRead(
                    credential=credential,
                    reader_id=reader_id
                )
                logger.info(f"Serial QR Read event: {event}")
                return event
        elif scud_event.type == EventType.INPUT_SIGNAL:
            # Обработка событий от датчиков прохода
            from scud_lgtu.domain.events import PassageDetected
            zone = scud_event.payload.get("zone")
            direction = scud_event.payload.get("direction")
            duration = scud_event.payload.get("duration")
            token = scud_event.payload.get("token")
            if zone and direction and duration is not None:
                event = PassageDetected(
                    direction=direction,
                    zone=zone,
                    duration=duration,
                    token=token
                )
                logger.info(f"Passage Detected event: {event}")
                return event
        
        logger.debug(f"Unknown event type: {scud_event.type}")
        return None
    
    def _initialize_button_states(self) -> None:
        """Initialize button states to avoid false edge detection."""
        logger.debug("Initializing button states")
        try:
            from scud_lgtu.application.handlers.mux import _button_states
            # Initialize all buttons to None so first event is treated as initial state
            button_names = ["button_1", "button_2", "button_3"]
            for name in button_names:
                _button_states[name] = None
            logger.debug(f"Initialized button states: {_button_states}")
        except Exception as e:
            logger.error(f"Error initializing button states: {e}")
    
    def _initialize_outputs(self) -> None:
        """Initialize all outputs to safe state (relays closed)."""
        logger.debug("Initializing outputs to safe state")
        try:
            # Set all relays to closed (False) через публичный интерфейс
            safe_states = {
                "rel1": False,
                "rel2": False,
                "w1_green": False,
                "w1_red": False,
                "w2_green": False,
                "w2_red": False,
                "w1_beep": False,
                "w2_beep": False,
                "buz": False,
                "pult_buzz": False,
                "pult_l1": False,
                "pult_l2": False,
                "pult_l3": False,
                "od1": False,
                "od2": False,
            }
            self._engine.set_output_mask(safe_states)
            logger.debug(f"Initialized outputs to safe state: {safe_states}")
        except Exception as e:
            logger.error(f"Error initializing outputs: {e}")
    
    def run(self) -> None:
        """Run the main application loop."""
        logger.info("LGTUApplication: starting")
        self._running = True
        
        # Start event loop for async operations
        self._start_event_loop()
        
        # Initialize outputs to safe state (all relays closed)
        self._initialize_outputs()
        
        # Initialize button states to avoid false edge detection
        self._initialize_button_states()
        
        # Get event queue from engine
        event_queue = self._engine.get_event_queue()
        
        try:
            while self._running:
                # Process events from engine
                try:
                    scud_event = event_queue.get(timeout=0.1)
                    logger.debug(f"Received ScudEvent from engine: {scud_event}")
                    domain_events = self._convert_scud_event_to_domain(scud_event)
                    
                    # Обработка списка событий или одного события
                    if domain_events:
                        if isinstance(domain_events, list):
                            for event in domain_events:
                                self._event_bus.publish(event)
                        else:
                            self._event_bus.publish(domain_events)
                except queue.Empty:
                    # Нормальное поведение - очередь пуста
                    pass
                except Exception as e:
                    logger.error(f"Error processing event: {e}")
                
                # Tick turnstile state machine
                now = time.time()
                commands = self._turnstile.tick(now)
                # Apply commands to shift register
                if commands:
                    # Собираем все команды в словарь состояний для сдвигового регистра
                    output_states = {}
                    for cmd in commands:
                        output_states[cmd.name] = cmd.state

                    # Отправляем состояния в сдвиговый регистр через PinControllerThread
                    if output_states:
                        try:
                            # Получаем доступ к PinControllerThread через engine
                            pct = self._engine._pct
                            if pct:
                                pct.set_mask(output_states)
                        except Exception as e:
                            logger.error(f"Error sending to shift register: {e}")
                
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
