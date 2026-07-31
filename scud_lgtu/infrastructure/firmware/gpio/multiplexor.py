"""
Поток опроса мультиплексора (Multiplexer) системы СКУД.

Этот модуль реализует поток для периодического опроса мультиплексора, который
мультиплексирует входные сигналы: датчики, кнопки, тревога. Поток перебирает
все адреса мультиплексора, читает входной пин и кладёт сырые состояния в
`output_queue`.

Преобразованием сырых состояний в доменные события занимается `MuxEventMapper`.

Классы
-------
- MuxEventMapper: преобразование сырых состояний в ScudEvent-ы
- Multiplexer: поток опроса мультиплексора

Методы Multiplexer
-------------------
- __init__: инициализировать воркер мультиплексора с контроллером, пинами и очередями
- run: главный цикл опроса мультиплексора
- _load_input_names_from_resolver: загрузить мапинг входов из конфигурации
"""

import threading
import logging
import time
from queue import Queue, Full
from typing import Any, Tuple, Optional

from scud_lgtu.infrastructure.firmware.gpio.controller import GpiodPinController
from scud_lgtu.infrastructure.persistence.event_store import ScudEvent, EventType, EventSource

logger = logging.getLogger(__name__)


class MuxEventMapper:
    """Преобразует сырые данные мультиплексора в доменные ScudEvent-ы."""

    def __init__(self, config: Optional[dict] = None) -> None:
        """Инициализировать маппер с конфигурацией входов мультиплексора."""
        self._mux_inputs = (config or {}).get("mux", {}).get("inputs", {})

    def map_changes(self, prev: dict, curr: dict) -> list[ScudEvent]:
        """По разнице состояний сформировать button_pressed и alarm_changed события."""
        events: list[ScudEvent] = []
        for input_name, state in curr.items():
            if prev.get(input_name) == state:
                continue
            cfg = self._mux_inputs.get(input_name, {})
            active_high = cfg.get("active_high", False)
            # Кнопки и датчики — low active (0 = активно), тревога — high active (1 = активно)
            state_bool = (state == 1) if active_high else (state == 0)

            if input_name == "alarm":
                events.append(
                    ScudEvent(
                        type=EventType.ALARM_CHANGED,
                        source=EventSource.MUX,
                        payload={"active": state_bool},
                    )
                )
            elif input_name.startswith("button_"):
                events.append(
                    ScudEvent(
                        type=EventType.BUTTON_PRESSED,
                        source=EventSource.MUX,
                        payload={"button_id": input_name, "state": state_bool},
                    )
                )
            else:
                direction = cfg.get("direction")
                zone = cfg.get("zone")
                if direction and zone and input_name in prev:
                    prev_val = prev.get(input_name)
                    prev_bool = (prev_val == 1) if active_high else (prev_val == 0)
                    if prev_bool and not state_bool:
                        events.append(
                            ScudEvent(
                                type=EventType.INPUT_SIGNAL,
                                source=EventSource.MUX,
                                payload={
                                    "event": "detected",
                                    "zone": zone,
                                    "direction": direction,
                                    "duration": 0.0,
                                },
                            )
                        )
        return events


class Multiplexer:
    """
    Поток опроса мультиплексора.

    Parameters
    ----------
    controller : GpiodPinController
        Инициализированный контроллер GPIO.
    input_pin : str
        Имя пина чтения данных с мультиплексора (например, ``'PL11'``).
    output_pins : tuple of str
        Адресные пины мультиплексора (например, ``('PA6', 'PA11', 'PA12')``).
    output_queue : queue.Queue
        Очередь, в которую кладутся считанные состояния.
    lock : threading.Lock
        Общий лок с ShiftRegWorker для защиты GPIO от гонки.
    stop_event : threading.Event
        Событие остановки — при установке поток завершает работу.
    poll_interval : float, optional
        Пауза между полными проходами по адресам (секунды). По умолчанию 0.02 (будет переопределено из конфига).
    addr_settle_s : float, optional
        Время стабилизации выхода мультиплексора после смены адреса (секунды).
        По умолчанию 500 мкс (с запасом относительно ~200 мкс спада сигнала).
        Задержка выполняется внутри общего лока с ShiftRegWorker,
        чтобы исключить гонку на shared-пинах (PA6 и др.).
    config : dict, optional
        Конфигурация для автоматического мапинга входов мультиплексора.
        Формат: ``{'mux_inputs': {0: 'input_name_0', 1: 'input_name_1', ...}}``.
        Если не указан - используются адреса (0-7).
    """

    def __init__(
        self,
        controller: GpiodPinController,
        input_pin: str,
        output_pins: Tuple[str, ...],
        output_queue: Queue,
        lock: threading.Lock,
        stop_event: threading.Event,
        poll_interval: float,
        addr_settle_s: float,
        button_debounce_s: float,
        resolver: Optional[Any] = None,
    ):
        """
        Инициализировать воркер мультиплексора.

        Parameters
        ----------
        controller : GpiodPinController
            Инициализированный контроллер GPIO
        input_pin : str
            Имя пина чтения данных с мультиплексора
        output_pins : tuple of str
            Адресные пины мультиплексора
        output_queue : Queue
            Очередь для считанных состояний
        lock : threading.Lock
            Общий лок для защиты GPIO от гонки
        stop_event : threading.Event
            Событие остановки потока
        poll_interval : float, optional
            Пауза между полными проходами по адресам (секунды)
        addr_settle_s : float, optional
            Время стабилизации выхода мультиплексора (секунды)
        config : dict, optional
            Конфигурация для мапинга входов
        """
        self._controller = controller
        self._input_pin = input_pin
        self._output_pins = list(output_pins)
        self._output_queue = output_queue
        self._lock = lock
        self._stop_event = stop_event
        self._poll_interval = poll_interval
        self._addr_settle_s = addr_settle_s
        self._button_debounce_s = button_debounce_s
        self._n = len(output_pins)
        # Индексы для быстрого iter: [0, 1, 2, ...]
        self._indices = list(range(self._n))
        # Кэш предыдущего состояния для дельта-фильтрации
        self._prev_state: dict = {}
        self._stable_button_states: dict[str, int] = {}
        self._pending_button_states: dict[str, tuple[int, float]] = {}
        self._overflow_logged = False
        self._resolver = resolver

        # Мапинг входов по номерам с именами (опционально)
        self._input_names = {}
        if resolver:
            self._load_input_names_from_resolver()

    def _load_input_names_from_resolver(self) -> None:
        """Загрузить мапинг входов из ModuleResolver (mux.inputs)."""
        try:
            inputs = self._resolver.resolve("mux.inputs")
            for name, cfg in inputs.items():
                addr = cfg.get("addr")
                if addr is not None:
                    self._input_names[addr] = name
                    logger.debug(f"[Multiplexer] Мапинг: вход {addr} -> '{name}'")
        except Exception as e:
            logger.warning(f"[Multiplexer] Не удалось загрузить мапинг входов: {e}")

    def _filter_debounced_button_states(self, states: dict[str, int], now: float) -> dict[str, int]:
        """Вернуть состояния, публикуя кнопочные переходы только после debounce."""
        filtered = states.copy()
        for input_name, state in states.items():
            if not input_name.startswith("button_"):
                continue

            stable_state = self._stable_button_states.get(input_name)
            if stable_state is None:
                self._stable_button_states[input_name] = state
                continue

            if state == stable_state:
                self._pending_button_states.pop(input_name, None)
                filtered[input_name] = stable_state
                continue

            pending = self._pending_button_states.get(input_name)
            if pending is None or pending[0] != state:
                self._pending_button_states[input_name] = (state, now)
                filtered[input_name] = stable_state
                continue

            if now - pending[1] >= self._button_debounce_s:
                self._stable_button_states[input_name] = state
                self._pending_button_states.pop(input_name, None)
                filtered[input_name] = state
            else:
                filtered[input_name] = stable_state
        return filtered

    def _work_mux(self) -> None:
        """
        Один полный проход по всем адресам мультиплексора.

        Критически важно: set-адреса и read-вход должны выполняться **под одним
        захватом внешнего лока** — иначе ShiftRegister успеет изменить пины
        PA6/PA11/PA12 (которые одновременно SER_DATA и адресные пины) в
        промежутке между set и read, и мы прочитаем вход для неверного адреса.

        Последовательность для каждого из 2^n адресов:
          1. Захватываем ``self._lock`` (внешний, разделяемый с ShiftRegister).
          2. Устанавливаем адресные пины через ``set_outputs_bulk_nolock``
             (без внутреннего лока контроллера — мы уже под внешним).
          3. Спим ``addr_settle_s`` **внутри** внешнего лока.
             ShiftRegister заблокирован на это время, но задержка мала (300 мкс)
             и не мешает работе регистра между полными проходами мультиплексора.
          4. Читаем входной пин через ``read_pin_nolock``.
          5. Отпускаем лок.
        """
        buf: dict = {}
        for mask in range(2 ** self._n):
            # Формируем словарь {pin: bit} для текущей маски
            values = {
                self._output_pins[i]: (mask >> i) & 1
                for i in self._indices
            }

            # Один захват внешнего лока на весь цикл set → settle → read:
            # ShiftRegister не вмешается в середину последовательности.
            with self._lock:
                # Записываем адрес (nolock — внешний лок уже держим)
                self._controller.set_outputs_bulk_nolock(values)
                # Ждём стабилизации выхода мультиплексора (~200 мкс спада)
                time.sleep(self._addr_settle_s)
                # Читаем входной пин (nolock — внешний лок держим)
                input_state = self._controller.read_pin_nolock(self._input_pin)

            # Используем имя входа из мапинга, если есть
            input_name = self._input_names.get(mask, f"input_{mask}")
            buf[input_name] = input_state

        buf = self._filter_debounced_button_states(buf, time.monotonic())

        # Дельта-фильтр: отправляем только при изменении
        if buf != self._prev_state:
            self._prev_state = buf.copy()
            try:
                self._output_queue.put_nowait(buf)
            except Full:
                if not self._overflow_logged:
                    logger.warning("Multiplexer: output_queue переполнена, данные сброшены.")
                    self._overflow_logged = True

    def run(self) -> None:
        """
        Основной цикл потока мультиплексора.

        Запускается как target для ``threading.Thread``.
        Завершается при установке ``stop_event``.
        """
        logger.debug(
            "🔄 MuxWorker запущен (input=%s, outputs=%s, settle=%.0f мкс)",
            self._input_pin, self._output_pins, self._addr_settle_s * 1e6,
        )
        while not self._stop_event.is_set():
            try:
                self._work_mux()
            except Exception as e:
                logger.error("MuxWorker ошибка: %s", e, exc_info=True)
            # Короткая пауза между циклами, чтобы не перегружать CPU
            self._stop_event.wait(timeout=self._poll_interval)
        logger.debug("MuxWorker остановлен.")
