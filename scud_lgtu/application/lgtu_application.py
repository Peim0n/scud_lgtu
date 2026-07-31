"""
Основное приложение LGTU системы СКУД.

Этот модуль реализует основную логику приложения, связывающую инфраструктуру (ScudEngine)
с доменной логикой (TurnstileDevice, AccessPolicy, PassageTracker).
Приложение получает события от ScudEngine, преобразует их в доменные события
и передаёт устройству, которое возвращает команды. Команды выполняются асинхронно
через встроенный _CommandRunner.

Классы
-------
- _CommandRunner: асинхронный исполнитель команд устройства с приоритетами.
- LGTUApplication: основное приложение, реализующее чистую архитектуру.

Методы LGTUApplication
----------------------
- __init__: инициализировать приложение
- run: запустить главный цикл приложения
- stop: остановить приложение
- _process_domain_event: преобразовать событие в команду и передать исполнителю
- _convert_scud_event_to_domain: преобразовать событие ScudEngine в доменное событие
- _initialize_outputs: инициализировать все выходы в безопасное состояние
- _start_event_loop: запустить asyncio event loop в отдельном потоке
"""
import asyncio
import logging
import queue
import threading
import time
from enum import Enum
from typing import Any, List, Optional
from scud_lgtu.infrastructure.devices.turnstile.turnstile_device import TurnstileDevice
from scud_lgtu.infrastructure.devices.turnstile.commands import Command
from scud_lgtu.domain.access import AccessPolicy, PassageTracker
from scud_lgtu.domain.events import (
    QrRead, CardRead,
    PassageDetected,
    ButtonPressed,
    AccessGranted, AccessDenied, DeviceCommand, AlarmChanged, AdminCommand,
)
from scud_lgtu.domain.models import Credential, OutputCommand, Passage, AuthSession
from scud_lgtu.domain.enums import TokenTypeEnum, DirectionEnum, ResultEnum
from scud_lgtu.application.services.passage_service import PassageService
from scud_lgtu.application.services.sync_service import SyncService

logger = logging.getLogger(__name__)


class _CommandRunner:
    """Асинхронный запускатель команд устройства с приоритетами и явной остановкой."""

    def __init__(self, actuator: Any, event_source: Any = None, sound_output: Any = None):
        self._actuator = actuator
        self._event_source = event_source
        self._sound_output = sound_output
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._tasks: dict[str, asyncio.Task] = {}
        self._commands: dict[str, Command] = {}
        self._state_label: str = "idle"
        self._entry_relay: str = "entry_relay"
        self._exit_relay: str = "exit_relay"

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def set_relay_names(self, entry_relay: str, exit_relay: str) -> None:
        self._entry_relay = entry_relay
        self._exit_relay = exit_relay

    @property
    def state_label(self) -> str:
        return self._state_label

    def play_sound(self, effect: str) -> None:
        """Воспроизвести звук."""
        if self._sound_output is not None:
            self._sound_output.play(effect)

    def submit(self, command: Command) -> None:
        if self._loop is None or not self._loop.is_running():
            logger.warning("CommandRunner: event loop не запущен, команда отброшена")
            return
        asyncio.run_coroutine_threadsafe(self._schedule(command), self._loop)

    async def _schedule(self, command: Command) -> None:
        meta = command.meta
        for name in meta.conflicts:
            await self._stop_and_wait(name)
        await self._stop_and_wait(meta.name)
        if meta.state_label:
            self._state_label = meta.state_label
        task = self._loop.create_task(self._run(command))
        self._commands[meta.name] = command
        self._tasks[meta.name] = task

    async def _stop_and_wait(self, name: str, timeout: float = 0.5) -> None:
        old_command = self._commands.get(name)
        task = self._tasks.get(name)
        if old_command is None or task is None or task.done():
            self._commands.pop(name, None)
            self._tasks.pop(name, None)
            return
        old_command.request_stop()
        try:
            await asyncio.wait_for(task, timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning(f"CommandRunner: {name} не остановилась за {timeout}с, отменяем")
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def _run(self, command: Command) -> None:
        meta = command.meta
        try:
            await command.run(self)
        except asyncio.CancelledError:
            commands = command.cleanup()
            if commands:
                await self.apply(commands)
        except Exception:
            logger.exception(f"CommandRunner: ошибка в команде {meta.name}")
        finally:
            self._tasks.pop(meta.name, None)
            self._commands.pop(meta.name, None)
            if meta.end_state_label:
                self._state_label = meta.end_state_label

    async def apply(self, commands: List[OutputCommand]) -> None:
        if not commands:
            return
        if self._actuator is not None:
            for cmd in commands:
                try:
                    self._actuator.apply(cmd)
                except Exception as e:
                    logger.error(f"Error applying command {cmd}: {e}")

    async def stop_all(self) -> None:
        for command in list(self._commands.values()):
            command.request_stop()
        pending = [t for t in self._tasks.values() if not t.done()]
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        self._tasks.clear()
        self._commands.clear()
        if self._actuator is not None:
            for name in (self._entry_relay, self._exit_relay, "entry_green", "exit_green",
                         "entry_red", "exit_red", "main_buzzer"):
                try:
                    self._actuator.apply(OutputCommand(name=name, state=False))
                except Exception as e:
                    logger.error(f"Error applying safe state {name}: {e}")


class LGTUApplication:
    """Основное приложение LGTU, реализующее чистую архитектуру."""

    def __init__(
        self,
        event_source: Any,
        device_logic: TurnstileDevice,
        access_policy: AccessPolicy,
        passage_tracker: PassageTracker,
        passage_service: PassageService,
        sync_service: SyncService,
        actuator: Any,
        sound_output: Any = None,
        config: dict = None,
        devices: dict = None,
        qr_decoder: Any = None,
    ):
        """
        Инициализировать приложение LGTU.

        Parameters
        ----------
        event_source : Any
            Источник событий и управления оборудованием (ScudEngine)
        device_logic : TurnstileDevice
            Событийно-управляемая логика устройства (турникет/ворота/дверь)
        access_policy : AccessPolicy
            Политика доступа
        passage_tracker : PassageTracker
            Трекер проходов
        passage_service : PassageService
            Сервис журналирования проходов
        sync_service : SyncService
            Сервис синхронизации с бэкендом
        actuator : Any
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
        self._timings = config["timings"]
        self._devices = devices or {}
        self._running = False
        self._qr_decoder = qr_decoder
        self._device = device_logic
        self._access_policy = access_policy
        self._passage_tracker = passage_tracker
        self._passage_service = passage_service
        self._sync_service = sync_service
        self._actuator = actuator
        self._sound_output = sound_output

        # Исполнитель команд: отвечает за приоритеты, отмену и применение выходов
        self._executor = _CommandRunner(actuator, event_source, self._sound_output)
        self._executor.set_relay_names(device_logic.entry_relay, device_logic.exit_relay)

        # Состояние кнопки-модификатора Shift (оркестрация, не логика устройства)
        self._shift_pressed = False
        self._shift_used = False

        # Цикл событий для асинхронных операций
        self._loop = None
        self._loop_thread = None

    def _process_domain_event(self, event) -> None:
        """Превратить доменное событие в команду для устройства и отправить исполнителю."""
        device_event = self._to_device_event(event)
        if device_event is None:
            return

        # Проход зафиксирован — журналируем до обработки устройством
        if isinstance(device_event, PassageDetected):
            self._log_passage(device_event)

        command = self._device.handle(device_event)
        if command is not None:
            self._executor.submit(command)

    def _to_device_event(self, event) -> Optional[Any]:
        """События доступа/кнопок/тревоги превращаются в команды устройства.

        Во время тревоги игнорируем доступ и обычные кнопки.
        """
        if isinstance(event, (CardRead, QrRead)):
            if self._device.is_alarm_active:
                return None
            return self._check_access(event)

        if isinstance(event, ButtonPressed):
            if self._device.is_alarm_active:
                return None
            return self._map_button_event(event)

        if isinstance(event, AdminCommand):
            return DeviceCommand(command=event.command)

        if isinstance(event, AlarmChanged):
            return event

        if isinstance(event, PassageDetected):
            return event

        return None

    def _check_access(self, event) -> Optional[Any]:
        """Проверить учётные данные и вернуть AccessGranted/AccessDenied."""
        decision = self._access_policy.check(event.credential)
        reader_config = self._devices.get("readers", {}).get(event.reader_id, {})
        direction = reader_config.get("direction", "entry")
        token_prefix = "maxid" if isinstance(event, QrRead) else "cardid"
        token = f"{token_prefix}:{event.credential.value}"

        if decision.allowed:
            session = AuthSession(token=token, user_id=decision.user_id)
            session.direction = DirectionEnum.IN if direction == "entry" else DirectionEnum.OUT
            self._passage_tracker.track(session)
            return AccessGranted(direction=direction, token=token, user_id=decision.user_id)

        return AccessDenied(direction=direction)

    def _map_button_event(self, event: ButtonPressed) -> Optional[Any]:
        """Преобразовать нажатие кнопки в DeviceCommand с учётом Shift."""
        buttons = self._devices.get("buttons", {})
        button_config = None
        for cfg in buttons.values():
            if cfg.get("label") == event.button_id:
                button_config = cfg
                break

        if button_config is None:
            logger.debug(f"Кнопка не найдена в конфиге: {event.button_id}")
            return None

        action = button_config.get("action")
        if not action:
            logger.error(f"Кнопка {event.button_id} не имеет action")
            return None

        if action == "shift":
            if event.state:
                self._shift_pressed = True
                self._shift_used = False
                logger.info(f"Button {event.button_id}: Shift pressed")
            else:
                if self._shift_pressed and not self._shift_used:
                    self._shift_pressed = False
                    self._shift_used = False
                    return DeviceCommand(command="close")
                self._shift_pressed = False
                self._shift_used = False
            return None

        if self._shift_pressed:
            self._shift_used = True
            if action == "open_entry":
                return DeviceCommand(command="unlock_entry", state=event.state)
            if action == "open_exit":
                return DeviceCommand(command="unlock_exit", state=event.state)

        if action in ("open_entry", "open_exit"):
            if event.state:
                return DeviceCommand(command=action, state=True)
            return DeviceCommand(command="start_close_timer", state=False)

        return DeviceCommand(command=action, state=event.state)

    def _log_passage(self, event: PassageDetected) -> None:
        """Записать проход в EventLog."""
        direction_enum = DirectionEnum.IN if event.direction == "in" else DirectionEnum.OUT
        passage = Passage(
            direction=direction_enum,
            zone=event.zone,
            duration=event.duration,
            result=ResultEnum.PASS,
            token=event.token,
            user_id=event.user_id,
        )
        self._passage_service.log_passage(passage)

    def _start_event_loop(self) -> None:
        """Запустить цикл событий asyncio в отдельном потоке и привязать исполнителя команд."""
        def run_loop():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            self._executor.set_loop(self._loop)
            self._loop.run_forever()

        self._loop_thread = threading.Thread(target=run_loop, daemon=True)
        self._loop_thread.start()

    def _stop_event_loop(self) -> None:
        """Остановить цикл событий asyncio."""
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._loop_thread and self._loop_thread.is_alive():
            self._loop_thread.join(timeout=self._timings["thread_join_timeout_s"])

    def _get_reader_id(self, reader: str) -> str:
        """Получить reader_id из мапинга reader_names."""
        reader_names = self._config.get("mappings", {})
        return reader_names.get(reader, reader)

    def _decode_qr_credential(self, data: str) -> Credential:
        """Декодировать QR код в Credential.

        При любой ошибке декодирования возвращает Credential с самим QR-данными,
        чтобы доступ был явно запрещён через access_policy, а не игнорировался.
        """
        if self._qr_decoder is not None:
            try:
                qr_fields = self._qr_decoder.decode_url(data)
                max_id = qr_fields.get("max_id")
                if max_id is None:
                    logger.error(f"QR код не содержит max_id: {data}")
                    return Credential(
                        token_type=TokenTypeEnum.MAXID,
                        value=str(data),
                        encrypted=False
                    )

                return Credential(
                    token_type=TokenTypeEnum.MAXID,
                    value=str(max_id),
                    encrypted=False
                )
            except Exception as e:
                logger.error(f"Ошибка декодирования QR кода: {e}")
                return Credential(
                    token_type=TokenTypeEnum.MAXID,
                    value=str(data),
                    encrypted=False
                )
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
        elif event_type == "button_pressed":
            button_id = scud_event.payload.get("button_id")
            state = scud_event.payload.get("state")
            if button_id is not None and state is not None:
                event = ButtonPressed(button_id=button_id, state=state)
                logger.info(f"Button Pressed event: {event}")
                return event
            return None
        elif event_type == "alarm_changed":
            active = scud_event.payload.get("active")
            if active is not None:
                event = AlarmChanged(active=active)
                logger.info(f"Alarm Changed event: {event}")
                return event
            return None
        elif event_type == "serial_data":
            # Обработка данных из serial порта (QR-код)
            data = scud_event.payload.get("data", "")
            if data:
                credential = self._decode_qr_credential(data)

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
                event = PassageDetected(
                    direction=direction,
                    zone=zone,
                    duration=duration,
                    token=token or self._device.current_token,
                    user_id=self._device.current_user_id
                )
                logger.info(f"Passage Detected event: {event}")
                return event

        logger.debug(f"Unknown event type: {scud_event.type}")
        return None


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

        # Получить очередь событий от источника
        event_queue = self._event_source.get_event_queue()

        try:
            while self._running:
                # Обрабатывать события от движка
                try:
                    scud_event = event_queue.get(timeout=self._timings["event_queue_timeout_s"])
                    logger.debug(f"Received ScudEvent from engine: {scud_event}")
                    domain_events = self._convert_scud_event_to_domain(scud_event)

                    # Обработка списка событий или одного события
                    if domain_events:
                        if isinstance(domain_events, list):
                            for event in domain_events:
                                self._process_domain_event(event)
                        else:
                            self._process_domain_event(domain_events)
                except queue.Empty:
                    # Нормальное поведение - очередь пуста
                    pass
                except Exception as e:
                    logger.error(f"Error processing event: {e}")

                # Периодический вызов сервиса синхронизации
                self._sync_service.tick(time.time())

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
