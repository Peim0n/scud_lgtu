"""
Главный оркестратор ScudEngine.

Запускает все hardware-модули как потоки и предоставляет бизнес-логике:
- event_queue — события от всех модулей
- cmd_queue   — команды к модулям
- is_healthy() — состояние потоков

Потоки:
- PinControllerThread (MuxWorker + ShiftRegWorker) на одном GpiodPinController
- WiegandReader — по одному на считыватель
- BackgroundSerialReader — по одному на порт
- InputSignalReader / OutputSignalWriter — сигналы
- CommandLoop — обработка входящих команд
- Watchdog — мониторинг живости потоков
"""

import logging
import threading
import time
import queue
from typing import Any, Optional

from .events import ScudEvent, ScudCommand, EventType, EventSource, CommandTarget, CommandAction
from .config import load as load_config
from .pin_controller import GpiodPinController
from .pin_controller_thread import PinControllerThread
from .wiegand_reader import WeigandReader, CardData
from .serial_reader import BackgroundSerialReader
from .signal_reader import InputSignalReader, InputData
from .signal_writer import OutputSignalWriter, OutputCommand, Value
from .passage_detector import PassageDetector

logger = logging.getLogger(__name__)


class Watchdog:
    """
    Следит за живостью hardware-потоков.

    При обнаружении мёртвого потока публикует событие error.
    Перезапуск пока не реализован — движок останавливается.
    """

    def __init__(
        self,
        threads: dict[str, threading.Thread],
        event_queue: queue.Queue,
        stop_event: threading.Event,
        check_interval: float,
        stop_timeout: float,
    ):
        """Инициализировать Watchdog для мониторинга потоков."""
        self._threads = threads
        self._event_queue = event_queue
        self._stop_event = stop_event
        self._check_interval = check_interval
        self._stop_timeout = stop_timeout
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """Запустить поток Watchdog."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="Watchdog", daemon=True)
        self._thread.start()
        logger.info("Watchdog запущен")

    def stop(self) -> None:
        """Остановить поток Watchdog."""
        self._stop_event.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=self._stop_timeout)

    def _run(self) -> None:
        """Цикл Watchdog: проверка живости потоков."""
        while not self._stop_event.wait(timeout=self._check_interval):
            for name, t in list(self._threads.items()):
                if t is None:
                    continue
                if not t.is_alive():
                    logger.error("Watchdog: поток %s не жив", name)
                    self._event_queue.put(
                        ScudEvent(
                            type=EventType.ERROR,
                            source=EventSource.WATCHDOG,
                            payload={"thread": name, "message": "thread is dead"},
                        )
                    )


class ScudEngine:
    """
    Единая точка входа для управления hardware СКУД.

    Пример
    ------
    ::

        engine = ScudEngine()
        engine.start()
        events = engine.get_event_queue()
        while True:
            event = events.get(timeout=1)
            print(event)
        engine.stop()
    """

    def __init__(self, config_path: Optional[str] = None):
        """Загрузить конфигурацию и подготовить очереди событий/команд."""
        self._cfg = load_config() if config_path is None else load_config()
        self._timings: dict[str, float] = self._cfg.get("timings", {})
        self._event_queue: queue.Queue = queue.Queue(maxsize=1000)
        self._cmd_queue: queue.Queue = queue.Queue(maxsize=100)

        self._stop_event = threading.Event()
        self._ctrl: Optional[GpiodPinController] = None
        self._pct: Optional[PinControllerThread] = None

        self._threads: dict[str, threading.Thread] = {}
        self._serial_readers: list[BackgroundSerialReader] = []
        self._wiegand_events: list[threading.Event] = []
        self._signal_events: list[threading.Event] = []
        self._signal_detector_thread: Optional[threading.Thread] = None
        self._passage_detectors: dict[str, PassageDetector] = {}
        self._output_writer: Optional[OutputSignalWriter] = None
        self._output_queue: Optional[queue.Queue] = None

        self._command_thread: Optional[threading.Thread] = None
        self._watchdog: Optional[Watchdog] = None
        self._last_mux_state: Optional[dict] = None

    def get_event_queue(self) -> queue.Queue:
        """Очередь событий для бизнес-логики."""
        return self._event_queue

    def send_command(self, command: ScudCommand) -> None:
        """Отправить команду в движок."""
        self._cmd_queue.put(command)

    def get_mux_state(self) -> Optional[dict]:
        """Вернуть последнее состояние мультиплексора, полученное от MuxWorker."""
        return self._last_mux_state

    def start(self) -> None:
        """Запустить все hardware-модули."""
        logger.info("ScudEngine: запуск…")
        self._stop_event.clear()

        self._init_gpio()
        self._start_workers()
        self._start_serial()
        self._start_wiegand()
        self._start_signals()
        self._start_command_loop()
        self._start_watchdog()

        logger.info("ScudEngine: запущен")

    def stop(self) -> None:
        """Остановить все потоки и освободить GPIO."""
        logger.info("ScudEngine: остановка…")
        self._stop_event.set()

        timeout = self._timings.get("thread_join_timeout_s", 5.0)

        # Останавливаем command loop
        if self._command_thread is not None and self._command_thread.is_alive():
            self._command_thread.join(timeout=timeout)

        # Останавливаем watchdog
        if self._watchdog is not None:
            self._watchdog.stop()

        # Останавливаем потоки и читатели
        for name, t in self._threads.items():
            if isinstance(t, BackgroundSerialReader):
                t.stop()
            elif isinstance(t, OutputSignalWriter):
                # OutputSignalWriter управляется через event
                pass
            elif t is not None and t.is_alive():
                t.join(timeout=timeout)

        # Wiegand
        for ev in self._wiegand_events:
            ev.clear()

        # Signals
        for ev in self._signal_events:
            ev.clear()

        # Output writer
        if self._output_writer is not None:
            self._output_writer.running.clear()

        # PinControllerThread
        if self._pct is not None:
            self._pct.stop(timeout=timeout)

        # GPIO controller
        if self._ctrl is not None:
            self._ctrl.close()

        logger.info("ScudEngine: остановлен")

    def is_healthy(self) -> bool:
        """True, если все hardware-потоки живы."""
        for t in self._threads.values():
            if t is None:
                continue
            if isinstance(t, BackgroundSerialReader):
                if not t._thread or not t._thread.is_alive():
                    return False
            elif not t.is_alive():
                return False
        return True

    def _init_gpio(self) -> None:
        """Настроить GPIO: адресные пины, вход мультиплексора, сдвиговый регистр."""
        cfg = self._cfg
        sr = cfg["shift"]
        mux = cfg["mux"]

        all_outputs = list(mux["addr_pins"]) + [sr["ser_data"], sr["ser_clk"], sr["ser_latch"]]
        modes: dict[str, str] = {mux["input_pin"]: "input"}
        for p in all_outputs:
            modes[p] = "output"

        self._ctrl = GpiodPinController()
        self._ctrl.open(modes, pull_ups=[mux["input_pin"]])
        self._ctrl.set_output_states(dict.fromkeys(all_outputs, 0))
        logger.info("GpiodPinController инициализирован")

    def _start_workers(self) -> None:
        """Запустить PinControllerThread с MuxWorker и ShiftRegWorker."""
        sr = self._cfg["shift"]
        mux = self._cfg["mux"]
        timings = self._cfg.get("timings", {})

        self._pct = PinControllerThread(
            controller=self._ctrl,
            mux_input=mux["input_pin"],
            mux_outputs=tuple(mux["addr_pins"]),
            shift_ser_data=sr["ser_data"],
            shift_ser_clk=sr["ser_clk"],
            shift_ser_latch=sr["ser_latch"],
            shift_reg_len=sr["reg_len"],
            mux_poll_interval=timings.get("mux_poll_interval_s", 0.02),
            mux_addr_settle_s=timings.get("mux_addr_settle_s", 500e-6),
            event_queue=self._event_queue,
        )
        self._pct.start()
        self._threads["mux_worker"] = self._pct._mux_thread
        self._threads["shift_reg_worker"] = self._pct._shift_thread
        logger.info("PinControllerThread запущен")

    def _start_serial(self) -> None:
        """Запустить фоновые читатели Serial-портов."""
        for i, s in enumerate(self._cfg.get("serial", [])):
            reader = BackgroundSerialReader(s["port"], s["baud"])
            q = reader.start()
            name = f"serial_{s['label']}"
            self._serial_readers.append(reader)
            self._threads[name] = reader
            self._serial_queue_loop(q, name)
            logger.info("Serial reader %s запущен", name)

    def _serial_queue_loop(self, q: queue.Queue, name: str) -> None:
        """Передать строки из Serial-очереди в общую event_queue."""
        timeout = self._timings.get("serial_queue_timeout_s", 0.2)

        def _loop() -> None:
            while not self._stop_event.is_set():
                try:
                    line = q.get(timeout=timeout)
                    self._event_queue.put(
                        ScudEvent(
                            type=EventType.SERIAL_DATA,
                            source=EventSource.SERIAL,
                            payload={"reader": name, "data": line},
                        )
                    )
                except queue.Empty:
                    continue

        t = threading.Thread(target=_loop, name=f"SerialBridge-{name}", daemon=True)
        t.start()
        self._threads[f"{name}_bridge"] = t

    def _start_wiegand(self) -> None:
        """Запустить Wiegand-читатели из конфигурации."""
        for i, w in enumerate(self._cfg.get("wiegand", [])):
            t, q, ev = WeigandReader.start(
                d0=w["d0"],
                d1=w["d1"],
                wiegand_type=w["type"],
                encrypted=w.get("encrypted", False),
                decrypt_key=w.get("decrypt_key"),
                bit_timeout=self._timings.get("wiegand_bit_timeout_s", 0.025),
                wait_timeout=self._timings.get("wiegand_wait_timeout_s", 0.005),
            )
            name = f"wiegand_{w['label']}"
            self._wiegand_events.append(ev)
            self._threads[name] = t
            self._wiegand_queue_loop(q, name)
            logger.info("Wiegand reader %s запущен", name)

    def _wiegand_queue_loop(self, q: queue.Queue, name: str) -> None:
        """Передать CardData из Wiegand-очереди в общую event_queue."""
        timeout = self._timings.get("event_queue_timeout_s", 0.2)

        def _loop() -> None:
            while not self._stop_event.is_set():
                try:
                    data: CardData = q.get(timeout=timeout)
                    self._event_queue.put(
                        ScudEvent(
                            type=EventType.CARD_READ,
                            source=EventSource.WIEGAND,
                            payload={
                                "reader": name,
                                "card_data": data.card_data,
                                "raw_data": data.raw_data,
                                "bit_sequence": data.bit_sequence,
                                "is_valid": data.is_valid,
                                "error_message": data.error_message,
                            },
                        )
                    )
                except queue.Empty:
                    continue

        t = threading.Thread(target=_loop, name=f"WiegandBridge-{name}", daemon=True)
        t.start()
        self._threads[f"{name}_bridge"] = t

    def _start_signals(self) -> None:
        """Создать детекторы проходов и запустить поток их обработки."""
        zones = self._cfg.get("passage", {}).get("zones", [])
        if not zones:
            logger.info("ScudEngine: зоны прохода не настроены")
            return

        for zone in zones:
            detector = PassageDetector(
                zone_label=zone["label"],
                inner_addr=int(zone["inner"]),
                outer_addr=int(zone["outer"]),
                event_queue=self._event_queue,
                passage_timeout=self._timings.get("passage_timeout_s", 2.0),
                blockage_timeout=self._timings.get("passage_blockage_timeout_s", 5.0),
            )
            self._passage_detectors[zone["label"]] = detector
            logger.info(
                "ScudEngine: зона прохода %s inner=A%d outer=A%d",
                zone["label"], zone["inner"], zone["outer"]
            )

        timeout = self._timings.get("mux_queue_timeout_s", 0.1)

        def _loop() -> None:
            while not self._stop_event.is_set():
                try:
                    states = self._pct.mux_output_queue.get(timeout=timeout)
                except queue.Empty:
                    states = None

                timestamp = time.time()
                if states is not None:
                    # Сохраняем последнее состояние для API /mux/state
                    self._last_mux_state = states
                    for detector in self._passage_detectors.values():
                        detector.on_mux_state(states, timestamp)

                for detector in self._passage_detectors.values():
                    detector.check_timeouts(timestamp)

        self._signal_detector_thread = threading.Thread(
            target=_loop, name="PassageDetector", daemon=True
        )
        self._signal_detector_thread.start()
        self._threads["passage_detector"] = self._signal_detector_thread
        logger.info("ScudEngine: датчики прохода запущены")

    def _start_command_loop(self) -> None:
        """Запустить поток обработки команд для ScudEngine."""
        timeout = self._timings.get("command_queue_timeout_s", 0.2)

        def _loop() -> None:
            while not self._stop_event.is_set():
                try:
                    cmd: ScudCommand = self._cmd_queue.get(timeout=timeout)
                    self._handle_command(cmd)
                except queue.Empty:
                    continue

        self._command_thread = threading.Thread(target=_loop, name="CommandLoop", daemon=True)
        self._command_thread.start()
        logger.info("CommandLoop запущен")

    def _handle_command(self, cmd: ScudCommand) -> None:
        """Выполнить команду, полученную из cmd_queue."""
        try:
            if cmd.target == CommandTarget.SHIFT.value and cmd.action == CommandAction.WRITE_SHIFT.value:
                value = int(cmd.payload.get("value", 0))
                if self._pct is not None:
                    self._pct.shift_input_queue.put(value)
                    self._event_queue.put(
                        ScudEvent(type=EventType.SHIFT_DONE, source=EventSource.SHIFT, payload={"value": value})
                    )

            elif cmd.target == CommandTarget.GPIO.value and cmd.action == CommandAction.SET_PIN.value:
                pin = cmd.payload["pin"]
                level = int(cmd.payload["level"])
                if self._ctrl is not None:
                    self._ctrl.write_pin(pin, level)

            elif cmd.target == CommandTarget.GPIO.value and cmd.action == CommandAction.SET_OUTPUTS_BULK.value:
                states = cmd.payload["states"]
                if self._ctrl is not None:
                    self._ctrl.set_outputs_bulk(states)

            elif cmd.target == CommandTarget.ENGINE.value and cmd.action == CommandAction.RESET.value:
                self._event_queue.put(
                    ScudEvent(type=EventType.HEALTH, source=EventSource.ENGINE, payload={"action": "reset_requested"})
                )

            elif cmd.target == CommandTarget.ENGINE.value and cmd.action == CommandAction.STOP.value:
                self._stop_event.set()

        except Exception as e:
            logger.exception("Ошибка обработки команды %s", cmd)
            self._event_queue.put(
                ScudEvent(
                    type=EventType.ERROR,
                    source=EventSource.ENGINE,
                    payload={"command": cmd, "error": str(e)},
                )
            )

    def _start_watchdog(self) -> None:
        """Запустить Watchdog для мониторинга всех потоков."""
        self._watchdog = Watchdog(
            self._threads,
            self._event_queue,
            self._stop_event,
            check_interval=self._timings.get("watchdog_check_interval_s", 2.0),
            stop_timeout=self._timings.get("watchdog_stop_timeout_s", 2.0),
        )
        self._watchdog.start()
