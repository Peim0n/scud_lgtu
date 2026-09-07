"""
Основное приложение LGTU системы СКУД.

Этот модуль реализует основную логику приложения, связывающую инфраструктуру (ScudEngine)
с доменной логикой (AccessDevice, AccessPolicy, PassageTracker).
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
from typing import Any

from app.application.services.passage_service import PassageService
from app.application.services.sync_service import SyncService
from app.domain.access import AccessPolicy, PassageTracker
from app.domain.access_device import AccessDevice
from app.domain.commands import Command
from app.domain.enums import DirectionEnum, ResultEnum, SeverityEnum, TokenTypeEnum
from app.domain.events import (
    AccessDenied,
    AccessGranted,
    AdminCommand,
    AlarmChanged,
    ButtonPressed,
    CardRead,
    DeviceCommand,
    PassageDetected,
    QrRead,
)
from app.domain.models import AuthSession, Credential, OutputCommand, Passage

logger = logging.getLogger(__name__)

# Внутренние типы токенов, которые нужно привести к типам проводного
# протокола (§5.5/§6.5 ТЗ: phone|phone_h|maxid|maxid_h|cardid|cardid_h)
# перед записью в журнал событий / отправкой на бэкенд.
WIRE_TOKEN_TYPE = {
    TokenTypeEnum.CARDID_PARTIAL_H.value: TokenTypeEnum.CARDID_H.value,
}


def _to_wire_token_type(token_type: str) -> str:
    """Привести внутренний тип токена к типу, ожидаемому бэкендом."""
    return WIRE_TOKEN_TYPE.get(token_type, token_type)


class _CommandRunner:
    """Асинхронный запускатель команд устройства с приоритетами и явной остановкой."""

    def __init__(self, actuator: Any, device: AccessDevice, event_source: Any = None, sound_output: Any = None, command_stop_timeout: float = 0.5):
        self._actuator = actuator
        self._device = device
        self._event_source = event_source
        self._sound_output = sound_output
        self._command_stop_timeout = command_stop_timeout
        self._loop: asyncio.AbstractEventLoop | None = None
        self._tasks: dict[str, asyncio.Task] = {}
        self._commands: dict[str, Command] = {}
        self._state_label: str = "idle"

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

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
        if self._loop is None:
            logger.warning("CommandRunner: event loop не инициализирован, команда отброшена")
            return
        meta = command.meta
        for name in meta.conflicts:
            # Пропускаем cleanup при переходе между эквивалентными состояниями
            skip_cleanup = False
            old_command = self._commands.get(name)
            if old_command is not None:
                old_label = old_command.meta.state_label
                new_label = meta.state_label
                if old_label is not None and new_label is not None and self._device.is_equivalent_state(old_label, new_label):
                    skip_cleanup = True
            await self._stop_and_wait(name, skip_cleanup=skip_cleanup)
        # Если команда с таким же именем уже выполняется, обновляем её вместо остановки
        old_command = self._commands.get(meta.name)
        task = self._tasks.get(meta.name)
        if old_command is not None and task is not None and not task.done():
            # Обновляем существующую команду
            old_command.refresh()
            logger.info(f"CommandRunner: обновлена команда {meta.name}")
            return
        await self._stop_and_wait(meta.name)
        if meta.state_label:
            self._state_label = meta.state_label
        task = self._loop.create_task(self._run(command))
        self._commands[meta.name] = command
        self._tasks[meta.name] = task

    async def _stop_and_wait(self, name: str, timeout: float | None = None, skip_cleanup: bool = False) -> None:
        if timeout is None:
            timeout = self._command_stop_timeout
        old_command = self._commands.get(name)
        task = self._tasks.get(name)
        if old_command is None or task is None or task.done():
            self._commands.pop(name, None)
            self._tasks.pop(name, None)
            return
        if skip_cleanup and hasattr(old_command, '_skip_cleanup'):
            old_command._skip_cleanup = True
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

    async def apply(self, commands: list[OutputCommand]) -> None:
        if not commands:
            return
        if self._actuator is not None:
            # Собрать все команды в один вызов set_output_mask
            masks = {cmd.name: cmd.state for cmd in commands}
            try:
                self._actuator._engine.set_output_mask(masks)
            except Exception:
                logger.exception("Error applying commands %s", masks)

    async def stop_all(self) -> None:
        for command in list(self._commands.values()):
            command.request_stop()
        pending = [t for t in self._tasks.values() if not t.done()]
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        self._tasks.clear()
        self._commands.clear()
        if self._actuator is not None:
            for name in self._device.output_names:
                try:
                    self._actuator.apply(OutputCommand(name=name, state=False))
                except Exception:
                    logger.exception("Error applying safe state %s", name)


class LGTUApplication:
    """Основное приложение LGTU, реализующее чистую архитектуру."""

    def __init__(
        self,
        event_source: Any,
        device_logic: AccessDevice,
        access_policy: AccessPolicy,
        passage_tracker: PassageTracker,
        passage_service: PassageService,
        sync_service: SyncService,
        actuator: Any,
        sound_output: Any = None,
        config: dict | None = None,
        devices: dict | None = None,
        qr_decoder: Any = None,
        periodic_services: list[Any] | None = None,
    ):
        """
        Инициализировать приложение LGTU.

        Parameters
        ----------
        event_source : Any
            Источник событий и управления оборудованием (ScudEngine)
        device_logic : AccessDevice
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
        periodic_services : list, optional
            Дополнительные сервисы с методом ``tick(now)``, вызываемым в
            основном цикле (KeySyncService, AccesspointInventoryService,
            обновление/ротация mTLS-сертификата и т.п.).
        """
        self._event_source = event_source
        self._config: dict[str, Any] = config or {}
        self._timings: dict[str, Any] = self._config.get("timings", {})
        self._devices: dict[str, Any] = devices or {}
        self._passage_zones: list[Any] = self._devices.get("passage_zones", [])
        self._running = False
        self._qr_decoder = qr_decoder
        self._device = device_logic
        self._access_policy = access_policy
        self._passage_tracker = passage_tracker
        self._passage_service = passage_service
        self._sync_service = sync_service
        self._periodic_services = periodic_services or []
        self._actuator = actuator
        self._sound_output = sound_output

        # Исполнитель команд: отвечает за приоритеты, отмену и применение выходов
        self._executor = _CommandRunner(
            actuator, device_logic, event_source, self._sound_output,
            command_stop_timeout=float(self._timings.get("command_stop_timeout_s", 0.5)),
        )

        # Состояние кнопки-модификатора Shift (оркестрация, не логика устройства)
        self._shift_pressed = False
        self._shift_used = False

        # Цикл событий для асинхронных операций
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_thread: threading.Thread | None = None

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

    def _to_device_event(self, event) -> Any | None:
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

    def _check_access(self, event) -> Any | None:
        """Проверить учётные данные и вернуть AccessGranted/AccessDenied.

        Для QR-кода может быть несколько credentials (max_id + phone) —
        проверяем каждый, доступ разрешён если хотя бы один прошёл.
        Также проверяется возраст QR-кода (timestamp) если задан qr_max_age_s.
        """
        credentials = getattr(event, "_all_credentials", None) or [event.credential]
        reader_config = self._devices.get("readers", {}).get(event.reader_id, {})
        direction = reader_config.get("direction", "entry")
        direction_enum = DirectionEnum.IN if direction == "entry" else DirectionEnum.OUT
        raw_input = getattr(event, "raw_data", None)

        def _log_denied(credential: Credential, reason: str) -> None:
            token_type = _to_wire_token_type(credential.token_type.value)
            self._passage_service.log_access_attempt(Passage(
                direction=direction_enum,
                zone="",
                duration=0.0,
                result=ResultEnum.DENIED,
                token=credential.value,
                token_type=token_type,
                raw_input=raw_input,
                severity=SeverityEnum.NOTICE.value,
            ))
            logger.info("Доступ отказан: %s:%s — %s", token_type, credential.value, reason)

        # Проверка возраста QR-кода
        if isinstance(event, QrRead) and event.timestamp is not None:
            max_age = self._config.get("access", {}).get("qr_max_age_s", 0)
            if max_age > 0:
                now = int(time.time())
                age = now - event.timestamp
                if age > max_age:
                    _log_denied(event.credential, f"возраст QR {age}s > {max_age}s")
                    return AccessDenied(direction=direction)

        for credential in credentials:
            decision = self._access_policy.check(credential)
            if decision.allowed:
                token_prefix = credential.token_type.value
                token = f"{token_prefix}:{credential.value}"
                session = AuthSession(token=token, direction=direction_enum, user_id=decision.user_id)
                self._passage_tracker.track(session)
                logger.info("Доступ разрешён: %s (user_id=%s)", token, decision.user_id)
                return AccessGranted(direction=direction, token=token, user_id=decision.user_id)

        # Все credentials проверены, ни один не прошёл
        _log_denied(event.credential, "нет в списке доступа")
        return AccessDenied(direction=direction)

    def _map_button_event(self, event: ButtonPressed) -> Any | None:
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
            return None

        return DeviceCommand(command=action, state=event.state)

    def _log_passage(self, event: PassageDetected) -> None:
        """Записать проход в EventLog."""
        direction_enum = DirectionEnum.IN if event.direction == "in" else DirectionEnum.OUT
        token_type, token_value = self._split_typed_token(event.token)
        passage = Passage(
            direction=direction_enum,
            zone=event.zone,
            duration=event.duration,
            result=ResultEnum.PASS,
            token=token_value,
            user_id=event.user_id,
            token_type=_to_wire_token_type(token_type) if token_type else None,
        )
        self._passage_service.log_passage(passage)

    @staticmethod
    def _split_typed_token(token: str | None) -> tuple[str | None, str | None]:
        """Разобрать токен вида 'token_type:value' (см. _check_access) на составляющие."""
        if not token or ":" not in token:
            return None, token
        token_type, _, value = token.partition(":")
        return token_type, value

    def _start_event_loop(self) -> None:
        """Запустить цикл событий asyncio в отдельном потоке и привязать исполнителя команд."""
        def run_loop():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            self._executor.set_loop(self._loop)
            self._loop.run_forever()

        thread = threading.Thread(target=run_loop, daemon=True)
        self._loop_thread = thread
        thread.start()

    def _stop_event_loop(self) -> None:
        """Остановить цикл событий asyncio."""
        if self._loop is not None and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._loop_thread is not None and self._loop_thread.is_alive():
            self._loop_thread.join(timeout=self._timings["thread_join_timeout_s"])

    def _get_reader_id(self, reader: str) -> str:
        """Получить reader_id из мапинга reader_names."""
        reader_names = self._config.get("mappings", {})
        return reader_names.get(reader, reader)

    def _decode_qr(self, data: str) -> tuple[list[Credential], dict, int | None]:
        """Декодировать QR код.

        Returns
        -------
        credentials : list[Credential]
            Список учётных данных (max_id, phone) для проверки доступа.
        qr_fields : dict
            Все поля из расшифрованного QR (max_id, phone, timestamp, age_category и т.д.).
        timestamp : int | None
            Unix timestamp генерации QR (для проверки возраста).
        """
        if self._qr_decoder is not None:
            try:
                qr_fields = self._qr_decoder.decode_url(data)
                credentials: list[Credential] = []

                max_id = qr_fields.get("max_id")
                if max_id is not None:
                    credentials.append(Credential(
                        token_type=TokenTypeEnum.MAXID,
                        value=str(max_id),
                        encrypted=False
                    ))

                phone = qr_fields.get("phone")
                if phone is not None:
                    credentials.append(Credential(
                        token_type=TokenTypeEnum.PHONE,
                        value=str(phone),
                        encrypted=False
                    ))

                if not credentials:
                    logger.error(f"QR код не содержит max_id/phone: {data}")
                    return ([Credential(
                        token_type=TokenTypeEnum.MAXID,
                        value=str(data),
                        encrypted=False
                    )], {}, None)

                ts = qr_fields.get("timestamp")
                return credentials, qr_fields, ts
            except Exception:
                logger.exception("Ошибка декодирования QR кода")
                return ([Credential(
                    token_type=TokenTypeEnum.MAXID,
                    value=str(data),
                    encrypted=False
                )], {}, None)
        else:
            logger.warning("QR decoder недоступен, используется URL как credential value")
            return ([Credential(
                token_type=TokenTypeEnum.MAXID,
                value=str(data),
                encrypted=False
            )], {}, None)

    def _convert_scud_event_to_domain(self, scud_event) -> Any | None:
        """Преобразовать ScudEvent в доменное событие."""
        logger.debug(f"Converting ScudEvent: type={scud_event.type}, source={scud_event.source}, payload={scud_event.payload}")

        event_type = scud_event.type
        if isinstance(event_type, Enum):
            event_type = event_type.value

        event: Any | None = None

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
                reader_id=reader_id,
                raw_data=scud_event.payload.get("data"),
            )
            logger.info(f"QR Read event: {event}")
            return event
        elif event_type == "card_read":
            # card_data приходит от Wiegand-ридера (ЭРА и аналоги) уже
            # частично хешированным: SHA256(PAN)+HMAC(STATIC_KEY), обрезанным
            # до 8 байт под Wiegand-кадр. Поэтому тип — CARDID_PARTIAL_H, а не
            # "сырой" CARDID: LocalAccessCache довычислит только финальный
            # HMAC(..., DYNAMIC_KEY) перед сравнением со списком cardid_h.
            credential = Credential(
                token_type=TokenTypeEnum.CARDID_PARTIAL_H,
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
                # Логируем нажатия всех кнопок и отпускание Shift
                if state:
                    logger.info(f"Button pressed: {button_id}")
                elif button_id == "button_3":
                    logger.info(f"Button released: {button_id}")
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
                credentials, qr_fields, qr_timestamp = self._decode_qr(data)

                reader = scud_event.payload.get("reader", "unknown")
                reader_id = self._get_reader_id(reader)
                event = QrRead(
                    credential=credentials[0],
                    reader_id=reader_id,
                    qr_fields=qr_fields,
                    timestamp=qr_timestamp,
                    raw_data=data,
                )
                event._all_credentials = credentials  # type: ignore[attr-defined]
                logger.info(f"Serial QR Read event: {event}")
                return event
        elif event_type == "input_signal":
            # Обработка событий от датчиков прохода
            sensor = scud_event.payload.get("sensor")
            if sensor:
                # Определяем направление и зону по имени сенсора из passage_zones
                direction = None
                zone = None
                for zone_config in self._passage_zones:
                    if zone_config.get("inner") == sensor:
                        direction = "in"
                        zone = zone_config.get("label")
                        break
                    elif zone_config.get("outer") == sensor:
                        direction = "out"
                        zone = zone_config.get("label")
                        break
                if direction and zone:
                    event = PassageDetected(
                        direction=direction,
                        zone=zone,
                        duration=0.0,  # Мультиплексор не измеряет длительность
                        token=self._device.current_token,
                        user_id=self._device.current_user_id
                    )
                    logger.info(f"[PassageDetected] direction={direction}, zone={zone}, token={self._device.current_token}, user_id={self._device.current_user_id}")
                    return event

        elif event_type == "error":
            # Аварийное событие от инфраструктуры (сейчас — только Watchdog,
            # см. infrastructure/engine.py). Своего доменного события у этого
            # типа нет — просто журналируем как системное (event_type=system,
            # п. 5.5 ТЗ), чтобы оно дошло до бэкенда при следующей
            # синхронизации (§6.5 ресурс event), а не терялось молча.
            message = scud_event.payload.get("message", "unknown error")
            source = scud_event.payload.get("thread") or (
                scud_event.source.value if hasattr(scud_event.source, "value") else scud_event.source
            )
            self._passage_service.log_system_event(
                description=f"[{source}] {message}", severity="critical",
            )
            return None

        logger.debug(f"Unknown event type: {scud_event.type}")
        return None


    def _initialize_outputs(self) -> None:
        """Инициализировать все настроенные выходы сдвигового регистра в безопасное (выключенное) состояние."""
        logger.debug("Initializing outputs to safe state")
        try:
            shift_cfg = self._config.get("shift_register", {})
            pins_cfg = shift_cfg.get("pins", {})
            # Собрать все выходы в один вызов set_output_mask
            masks = {name: False for name in pins_cfg}
            self._actuator._engine.set_output_mask(masks)
            logger.debug(f"Initialized outputs to safe state: {list(pins_cfg)}")
        except Exception:
            logger.exception("Error initializing outputs")

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
                except Exception:
                    logger.exception("Error processing event")

                # Периодический вызов сервисов синхронизации с бэкендом
                now = time.time()
                self._sync_service.tick(now)
                for service in self._periodic_services:
                    try:
                        service.tick(now)
                    except Exception:
                        logger.exception("LGTUApplication: ошибка периодического сервиса %s", service)

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

    def send_admin_command(self, command: str) -> None:
        """Отправить админ-команду напрямую в доменную логику."""
        logger.info(f"LGTUApplication: admin command '{command}'")
        self._process_domain_event(AdminCommand(command=command))
