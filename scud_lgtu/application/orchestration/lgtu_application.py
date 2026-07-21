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
from enum import Enum
from typing import Any, Optional
from scud_lgtu.domain.turnstile.services.turnstile import TurnstileState
from scud_lgtu.domain.access.ports.ports import Actuator
from scud_lgtu.domain.access.services.services import AccessPolicy, PassageTracker
from scud_lgtu.domain.common.events.events import QrRead, CardRead, MuxInputChanged, PassageDetected, PassageStarted, PassageSensorsCleared
from scud_lgtu.domain.common.models.models import Credential, OutputCommand
from scud_lgtu.domain.common.enums.enums import TokenTypeEnum
from scud_lgtu.application.events.event_bus import EventBus
from scud_lgtu.application.services.passage_service import PassageService
from scud_lgtu.application.services.sync_service import SyncService
from scud_lgtu.application.handlers.credential import handle_credential
from scud_lgtu.application.handlers.passage import handle_passage_detected, handle_passage_started, handle_passage_cleared
from scud_lgtu.application.handlers.mux import handle_mux_input_changed
from scud_lgtu.application.handlers.alarm import handle_alarm_changed
from scud_lgtu.application.handlers.button import handle_button_pressed

logger = logging.getLogger(__name__)


class LGTUApplication:
    """Основное приложение LGTU, реализующее чистую архитектуру."""

    def __init__(
        self,
        event_source: Any,
        turnstile: TurnstileState,
        access_policy: AccessPolicy,
        passage_tracker: PassageTracker,
        event_bus: EventBus,
        passage_service: PassageService,
        sync_service: SyncService,
        actuator: Actuator,
        config: dict,
        devices: dict = None,
        qr_decoder: Any = None,
    ):
        """
        Инициализировать приложение LGTU.

        Parameters
        ----------
        event_source : Any
            Источник событий и управления оборудованием (ScudEngine)
        turnstile : TurnstileState
            Состояние турникета
        access_policy : AccessPolicy
            Политика доступа
        passage_tracker : PassageTracker
            Трекер проходов
        event_bus : EventBus
            Шина событий
        passage_service : PassageService
            Сервис журналирования проходов
        sync_service : SyncService
            Сервис синхронизации с бэкендом
        actuator : Actuator
            Порт актуатора выходов
        config : dict
            Конфигурация
        devices : dict, optional
            Мапинг устройств из конфига
        qr_decoder : Any, optional
            Декодер QR-кодов
        """
        self._event_source = event_source
        self._config = config
        self._devices = devices or {}
        self._running = False
        self._qr_decoder = qr_decoder
        self._turnstile = turnstile
        self._access_policy = access_policy
        self._passage_tracker = passage_tracker
        self._event_bus = event_bus
        self._passage_service = passage_service
        self._sync_service = sync_service
        self._actuator = actuator

        # Цикл событий для асинхронных операций
        self._loop = None
        self._loop_thread = None

        # Зарегистрировать обработчики
        self._register_handlers()

    def _register_handlers(self) -> None:
        """Зарегистрировать обработчики событий."""
        # Зарегистрировать обработчики доменных событий
        self._event_bus.subscribe("QrRead", lambda e: handle_credential(
            e, self._turnstile, self._access_policy, self._passage_tracker, self._event_bus, self._devices, token_prefix="maxid"
        ))
        self._event_bus.subscribe("CardRead", lambda e: handle_credential(
            e, self._turnstile, self._access_policy, self._passage_tracker, self._event_bus, self._devices, token_prefix="cardid"
        ))
        self._event_bus.subscribe("PassageDetected", lambda e: handle_passage_detected(
            e, self._turnstile, self._passage_tracker, self._event_bus, self._passage_service, self._devices
        ))
        self._event_bus.subscribe("PassageStarted", lambda e: handle_passage_started(e, self._turnstile))
        self._event_bus.subscribe("PassageSensorsCleared", lambda e: handle_passage_cleared(e, self._turnstile, self._event_bus))
        self._event_bus.subscribe("MuxInputChanged", lambda e: handle_mux_input_changed(e, self._event_bus, self._turnstile))
        self._event_bus.subscribe("AlarmChanged", lambda e: handle_alarm_changed(e, self._turnstile, self._event_bus))
        self._event_bus.subscribe("ButtonPressed", lambda e: handle_button_pressed(e, self._turnstile, self._event_bus, self._devices))
        self._event_bus.subscribe("OutputCommandsGenerated", lambda e: self._handle_output_commands(e))

    def _handle_output_commands(self, event) -> None:
        """Обработать событие с командами для выхода."""
        from scud_lgtu.domain.common.events.events import OutputCommandsGenerated
        if isinstance(event, OutputCommandsGenerated):
            # Собираем все команды в словарь состояний для сдвигового регистра
            output_states = {}
            for cmd in event.commands:
                output_states[cmd.name] = cmd.state

            # Поставить/снять детекторы прохода в зависимости от открытого направления.
            # Реагируем только на команды реле; служебные команды (например, выключение бипера) не трогают охрану.
            if self._event_source is not None and hasattr(self._event_source, "arm_passage_detectors"):
                entry_changed = self._turnstile.entry_relay in output_states
                exit_changed = self._turnstile.exit_relay in output_states
                entry_on = output_states.get(self._turnstile.entry_relay, False) if entry_changed else None
                exit_on = output_states.get(self._turnstile.exit_relay, False) if exit_changed else None

                # Если открытие было по кнопке — у нас нет активной сессии, разрешаем любое направление.
                # При открытии картой/QR ожидаем направление соответствующего считывателя.
                has_session = self._turnstile.current_token is not None

                if entry_on:
                    self._event_source.arm_passage_detectors("in" if has_session else None)
                elif exit_on:
                    self._event_source.arm_passage_detectors("out" if has_session else None)
                elif (entry_changed and entry_on is False) or (exit_changed and exit_on is False):
                    self._event_source.disarm_passage_detectors()

            # Отправляем состояния в сдвиговый регистр через порт Actuator
            if output_states and self._actuator is not None:
                for cmd in event.commands:
                    try:
                        self._actuator.apply(cmd)
                    except Exception as e:
                        logger.error(f"Error sending to shift register: {e}")

    def _start_event_loop(self) -> None:
        """Запустить цикл событий asyncio в отдельном потоке."""
        def run_loop():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            self._event_bus.set_event_loop(self._loop)
            self._loop.run_forever()

        self._loop_thread = threading.Thread(target=run_loop, daemon=True)
        self._loop_thread.start()

    def _stop_event_loop(self) -> None:
        """Остановить цикл событий asyncio."""
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._loop_thread and self._loop_thread.is_alive():
            self._loop_thread.join(timeout=2.0)

    def _get_reader_id(self, reader: str) -> str:
        """Получить reader_id из мапинга reader_names."""
        reader_names = self._config.get("mappings", {})
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
        """Преобразовать ScudEvent в доменное событие."""
        logger.debug(f"Converting ScudEvent: type={scud_event.type}, source={scud_event.source}, payload={scud_event.payload}")

        event_type = scud_event.type
        if isinstance(event_type, Enum):
            event_type = event_type.value

        if event_type == "qr_read":
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
        elif event_type == "card_read":
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
        elif event_type == "mux_changed":
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
        elif event_type == "serial_data":
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
        elif event_type == "input_signal":
            # Обработка событий от датчиков прохода
            zone = scud_event.payload.get("zone")
            direction = scud_event.payload.get("direction")
            duration = scud_event.payload.get("duration")
            token = scud_event.payload.get("token")
            signal_event = scud_event.payload.get("event", "completed")
            if zone and direction and duration is not None:
                # Если детектор не знает токен, берём его из текущей сессии турникета
                current_token = token or self._turnstile.current_token
                current_user_id = self._turnstile.current_user_id
                if signal_event == "started":
                    event = PassageStarted(
                        zone=zone,
                        direction=direction,
                        first_sensor=scud_event.payload.get("outer_name") if direction == "in" else scud_event.payload.get("inner_name")
                    )
                    logger.info(f"Passage Started event: {event}")
                elif signal_event == "cleared":
                    event = PassageSensorsCleared(zone=zone)
                    logger.info(f"Passage Sensors Cleared event: {event}")
                else:
                    event = PassageDetected(
                        direction=direction,
                        zone=zone,
                        duration=duration,
                        token=current_token,
                        user_id=current_user_id
                    )
                    logger.info(f"Passage Detected event: {event}")
                return event

        logger.debug(f"Unknown event type: {scud_event.type}")
        return None

    def _initialize_button_states(self) -> None:
        """Инициализировать состояния кнопок, чтобы избежать ложного срабатывания."""
        logger.debug("Initializing button states")
        try:
            from scud_lgtu.application.handlers.mux import _button_states
            # Инициализировать все кнопки из конфига, чтобы первое событие считалось начальным состоянием
            mux_inputs = self._config.get("mux", {}).get("inputs", {})
            button_names = [name for name in mux_inputs.keys() if name.startswith("button_")]
            for name in button_names:
                _button_states[name] = None
            logger.debug(f"Initialized button states: {_button_states}")
        except Exception as e:
            logger.error(f"Error initializing button states: {e}")

    def _initialize_outputs(self) -> None:
        """Инициализировать все настроенные выходы сдвигового регистра в безопасное (выключенное) состояние."""
        logger.debug("Initializing outputs to safe state")
        try:
            shift_cfg = self._config.get("shift_register", {})
            pins_cfg = shift_cfg.get("pins", {})
            for name in pins_cfg:
                self._actuator.apply(OutputCommand(name=name, state=False))
            logger.debug(f"Initialized outputs to safe state: {list(pins_cfg)}")
        except Exception as e:
            logger.error(f"Error initializing outputs: {e}")

    def run(self) -> None:
        """Запустить главный цикл приложения."""
        logger.info("LGTUApplication: starting")
        self._running = True

        # Запустить цикл событий для асинхронных операций
        self._start_event_loop()

        # Инициализировать выходы в безопасное состояние (все реле закрыты)
        self._initialize_outputs()

        # Инициализировать состояния кнопок, чтобы избежать ложного срабатывания
        self._initialize_button_states()

        # Получить очередь событий от источника
        event_queue = self._event_source.get_event_queue()

        try:
            while self._running:
                # Обрабатывать события от движка
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

                # Тактировать конечный автомат турникета
                now = time.time()
                commands = self._turnstile.tick(now)
                # Применить команды к сдвиговому регистру
                if commands:
                    # Собираем все команды в словарь состояний для сдвигового регистра
                    output_states = {}
                    for cmd in commands:
                        output_states[cmd.name] = cmd.state

                    # Отправляем состояния в сдвиговый регистр через порт Actuator
                    if output_states and self._actuator is not None:
                        for cmd in commands:
                            try:
                                self._actuator.apply(cmd)
                            except Exception as e:
                                logger.error(f"Error sending to shift register: {e}")

                # Периодический вызов сервиса синхронизации
                self._sync_service.tick(now)

        except KeyboardInterrupt:
            logger.info("LGTUApplication: interrupted")
        finally:
            self.stop()

    def start(self) -> None:
        """Запустить источник событий (hardware)."""
        logger.info("LGTUApplication: starting event source")
        self._event_source.start()
        logger.info("LGTUApplication: event source started")

    def stop(self) -> None:
        """Остановить приложение."""
        logger.info("LGTUApplication: stopping")
        self._running = False
        self._stop_event_loop()
        logger.info("LGTUApplication: stopped")

    def shutdown(self) -> None:
        """Остановить приложение и источник событий."""
        self.stop()
        if self._event_source is not None:
            self._event_source.stop()

    def is_healthy(self) -> bool:
        """Проверить здоровье источника событий."""
        if self._event_source is None:
            return False
        if hasattr(self._event_source, "is_healthy"):
            return self._event_source.is_healthy()
        return True

    def get_event_queue(self) -> queue.Queue:
        """Вернуть очередь событий источника."""
        return self._event_source.get_event_queue()

    def send_command(self, command: Any) -> None:
        """Отправить команду источнику событий."""
        if self._event_source is not None and hasattr(self._event_source, "send_command"):
            self._event_source.send_command(command)
        else:
            logger.warning("LGTUApplication: send_command не поддерживается источником событий")
