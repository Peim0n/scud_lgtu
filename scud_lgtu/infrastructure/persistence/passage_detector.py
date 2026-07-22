"""
Простой детектор факта прохода по двум сенсорам.

- inner (sensor_1) = вход (in)
- outer (sensor_2) = выход (out)

При спадающем фронте сенсора, если направление совпадает с ожидаемым,
публикуется событие PassageDetected.
"""

import logging
import threading
from dataclasses import dataclass
from typing import Optional
from queue import Queue, Full

from scud_lgtu.infrastructure.persistence.event_store import ScudEvent, EventType, EventSource

logger = logging.getLogger(__name__)


@dataclass
class SensorState:
    """Состояние одного сенсора."""
    active: bool = False


class PassageDetector:
    """Детектор факта прохода по сенсорам мультиплексора."""

    def __init__(
        self,
        zone_label: str,
        inner_name: str,
        outer_name: str,
        event_queue: Queue,
        passage_timeout: float,
        blockage_timeout: float,
    ):
        self._zone = zone_label
        self._inner_name = inner_name
        self._outer_name = outer_name
        self._event_queue = event_queue
        # Таймауты больше не используются, оставлены для совместимости сигнатуры.
        self._passage_timeout = passage_timeout
        self._blockage_timeout = blockage_timeout

        self._inner = SensorState()
        self._outer = SensorState()
        self._armed = False
        self._expected_direction: Optional[str] = None
        self._lock = threading.Lock()

    def on_mux_state(self, states: dict, timestamp: float) -> None:
        """Обработать новое состояние мультиплексора."""
        inner_val = states.get(self._inner_name, 0)
        outer_val = states.get(self._outer_name, 0)

        with self._lock:
            self._update_sensor(self._inner_name, self._inner, inner_val, timestamp)
            self._update_sensor(self._outer_name, self._outer, outer_val, timestamp)

    def _sensor_direction(self, name: str) -> str:
        """inner = вход, outer = выход."""
        return "in" if name == self._inner_name else "out"

    def _update_sensor(self, name: str, state: SensorState, value: int, timestamp: float) -> None:
        """Обработать фронт сенсора. Инвертированная логика: 0 = активно."""
        if not value and not state.active:
            state.active = True
            logger.debug(f"[{self._zone}] {name} rising")
        elif value and state.active:
            state.active = False
            logger.debug(f"[{self._zone}] {name} falling")
            if not self._armed:
                return
            direction = self._sensor_direction(name)
            if self._expected_direction is None or self._expected_direction == direction:
                self._emit("completed", direction, timestamp)

    def check_timeouts(self, now: float) -> None:
        """Таймауты больше не используются."""
        pass

    def arm(self, direction: Optional[str] = None) -> None:
        """Установить ожидаемое направление прохода (None — любое)."""
        with self._lock:
            self._armed = True
            self._expected_direction = direction
            self._inner.active = False
            self._outer.active = False
        logger.debug(f"[PassageDetector {self._zone}] armed direction={direction}")

    def disarm(self) -> None:
        """Снять ожидание направления."""
        with self._lock:
            self._armed = False
            self._expected_direction = None
            self._inner.active = False
            self._outer.active = False
        logger.debug(f"[PassageDetector {self._zone}] disarmed")

    def _emit(self, event_type: str, direction: str, duration: float) -> None:
        """Опубликовать событие прохода в event_queue."""
        logger.info("[%s] Проход %s: %s", self._zone, event_type, direction)
        if self._event_queue is None:
            return
        try:
            self._event_queue.put_nowait(
                ScudEvent(
                    type=EventType.INPUT_SIGNAL,
                    source=EventSource.SIGNAL,
                    payload={
                        "event": event_type,
                        "zone": self._zone,
                        "direction": direction,
                        "duration": 0.0,
                        "inner_name": self._inner_name,
                        "outer_name": self._outer_name,
                    },
                )
            )
        except Full:
            logger.warning("PassageDetector: event_queue переполнена")
