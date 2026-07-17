"""
Детектор проходов по двум датчикам, подключенным к мультиплексору системы СКУД.

Этот модуль реализует детектор прохода по двум входам мультиплексора. Каждая зона прохода
имеет два датчика: INNER (ближе к зданию) и OUTER (ближе к улице). INNER → OUTER = проход
ВЫХОД (out), OUTER → INNER = проход ВХОД (in). MuxWorker периодически считывает состояния
всех адресов мультиплексора, PassageDetector получает эти состояния и отслеживает изменения.

Классы
-------
- SensorState: состояние одного датчика
- PassageDetector: детектор прохода по двум входам мультиплексора

Методы PassageDetector
----------------------
- __init__: инициализировать детектор прохода для одной зоны
- on_mux_state: обработать новое состояние мультиплексора
- _update_sensor: обновить состояние одного датчика (rising/falling)
- _maybe_start: запомнить первый сработавший датчик
- _check_completion: проверить завершение прохода по второму датчику
- check_timeouts: проверить таймауты: разворот или заслон
- _second_active: проверить, активен ли второй по порядку датчик
- _reset: сбросить текущее состояние прохода
- _emit: опубликовать событие прохода в event_queue
"""

import logging
import threading
import time
from dataclasses import dataclass
from typing import Optional
from queue import Queue, Full

from scud_lgtu.infrastructure.persistence.event_store import ScudEvent, EventType, EventSource

logger = logging.getLogger(__name__)


@dataclass
class SensorState:
    """Состояние одного датчика."""
    active: bool = False
    start_time: float = 0.0


class PassageDetector:
    """
    Детектор прохода по двум входам мультиплексора.

    Parameters
    ----------
    zone_label : str
        Название зоны прохода.
    inner_name : str
        Имя входа мультиплексора внутреннего датчика (из config.mux_inputs).
    outer_name : str
        Имя входа мультиплексора внешнего датчика (из config.mux_inputs).
    event_queue : queue.Queue
        Общая очередь событий ScudEngine.
    """

    def __init__(
        self,
        zone_label: str,
        inner_name: str,
        outer_name: str,
        event_queue: Optional[Queue] = None,
        passage_timeout: float = 2.0,
        blockage_timeout: float = 5.0,
    ):
        """Инициализировать детектор прохода для одной зоны."""
        self._zone = zone_label
        self._inner_name = inner_name
        self._outer_name = outer_name
        self._event_queue = event_queue
        self._passage_timeout = passage_timeout
        self._blockage_timeout = blockage_timeout

        self._inner = SensorState()
        self._outer = SensorState()
        self._first_sensor: Optional[str] = None
        self._first_time: float = 0.0

        self._lock = threading.Lock()

    def on_mux_state(self, states: dict, timestamp: float) -> None:
        """
        Обработать новое состояние мультиплексора.

        Parameters
        ----------
        states : dict
            Словарь состояний входов мультиплексора с именами из config.mux_inputs.
            Ключи - имена входов (например, "sensor_inner", "sensor_outer").
            Значения — 0 или 1.
        timestamp : float
            Время получения состояния.
        """
        inner_val = states.get(self._inner_name, 0)
        outer_val = states.get(self._outer_name, 0)

        logger.debug(f"[{self._zone}] Состояние датчиков: inner={inner_val}, outer={outer_val}")

        with self._lock:
            self._update_sensor("inner", self._inner, inner_val, timestamp)
            self._update_sensor("outer", self._outer, outer_val, timestamp)

    def _update_sensor(self, sensor: str, state: SensorState, value: int, timestamp: float) -> None:
        """Обновить состояние одного датчика (rising/falling)."""
        # Инвертированная логика: 1 = нет сигнала, 0 = есть сигнал
        if not value and not state.active:
            # Rising — начало импульса (датчик сработал)
            state.active = True
            state.start_time = timestamp
            self._maybe_start(sensor, timestamp)
        elif value and state.active:
            # Falling — конец импульса (датчик перестал срабатывать)
            state.active = False
            self._check_completion(sensor, timestamp)

    def _maybe_start(self, sensor: str, timestamp: float) -> None:
        """Запомнить первый сработавший датчик."""
        if self._first_sensor is None:
            self._first_sensor = sensor
            self._first_time = timestamp

    def _check_completion(self, sensor: str, timestamp: float) -> None:
        """Проверить завершение прохода по второму датчику."""
        if self._first_sensor is None:
            return

        if sensor != self._first_sensor:
            direction = "out" if self._first_sensor == "inner" else "in"
            duration = timestamp - self._first_time
            self._emit(direction, duration)
            self._reset()

    def check_timeouts(self, now: float) -> None:
        """Проверить таймауты: разворот или заслон."""
        with self._lock:
            if self._first_sensor is None:
                return

            elapsed = now - self._first_time

            if self._inner.active and self._outer.active and elapsed > self._blockage_timeout:
                self._emit("blockage", now - self._first_time)
                self._reset()
                return

            if elapsed > self._passage_timeout and not self._second_active():
                self._emit("turnback", now - self._first_time)
                self._reset()

    def _second_active(self) -> bool:
        """True, если второй по порядку датчик сейчас активен."""
        if self._first_sensor == "inner":
            return self._outer.active
        return self._inner.active

    def _reset(self) -> None:
        """Сбросить текущее состояние прохода."""
        self._first_sensor = None
        self._first_time = 0.0

    def _emit(self, direction: str, duration: float) -> None:
        """Опубликовать событие прохода в event_queue."""
        logger.info("[%s] Проход: %s, %.3f с", self._zone, direction, duration)
        if self._event_queue is None:
            return
        try:
            self._event_queue.put_nowait(
                ScudEvent(
                    type=EventType.INPUT_SIGNAL,
                    source=EventSource.SIGNAL,
                    payload={
                        "zone": self._zone,
                        "direction": direction,
                        "duration": duration,
                        "inner_name": self._inner_name,
                        "outer_name": self._outer_name,
                    },
                )
            )
        except Full:
            logger.warning("PassageDetector: event_queue переполнена")
