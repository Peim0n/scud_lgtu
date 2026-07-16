"""
Поток записи данных в сдвиговый регистр (ShiftRegWorker).

Ожидает числовые сообщения в ``input_queue``, при получении —
выдаёт биты MSB-first через линии SER_DATA / SER_CLK / SER_LATCH.

Принцип работы
--------------
1. Поток блокируется на ``input_queue.get(timeout=...)`` .
2. При получении числа (int) захватывает ``lock`` и вызывает
   :meth:`_work_shift` — последовательно записывает биты через GPIO.
3. Лок разделяется с MuxWorker, чтобы во время тиканья CLK мультиплексор
   не переключал адресные пины и наоборот.

Формат сообщений в input_queue
-------------------------------
``int`` — значение, которое нужно записать в регистр (MSB-first).
Ширина определяется параметром ``reg_len`` (обычно 16 бит).
"""

import threading
import logging
from queue import Queue, Empty, Full
from typing import Any, Optional

from .pin_controller import GpiodPinController
from .events import ScudEvent, EventType, EventSource

logger = logging.getLogger(__name__)


class ShiftRegWorker:
    """
    Поток записи данных в последовательный сдвиговый регистр.

    Parameters
    ----------
    controller : GpiodPinController
        Инициализированный контроллер GPIO.
    input_queue : queue.Queue
        Очередь входящих значений (int).
    ser_data_pin : str
        Имя пина SER_DATA (данные), например ``'PA6'``.
    ser_clk_pin : str
        Имя пина SER_CLK (тактирование), например ``'PA19'``.
    ser_latch_pin : str
        Имя пина SER_LATCH (защёлка), например ``'PA7'``.
    reg_len : int
        Разрядность регистра (биты), например ``16``.
    lock : threading.Lock
        Общий лок с MuxWorker.
    stop_event : threading.Event
        Событие остановки.
    event_queue : queue.Queue, optional
        Общая очередь событий. После успешной записи публикуется
        ``ScudEvent(type='shift_done', source='shift')``.
    """

    def __init__(
        self,
        controller: GpiodPinController,
        input_queue: Queue,
        ser_data_pin: str,
        ser_clk_pin: str,
        ser_latch_pin: str,
        reg_len: int,
        lock: threading.Lock,
        stop_event: threading.Event,
        event_queue: Optional[Queue] = None,
    ):
        """Инициализировать воркер сдвигового регистра."""
        self._controller = controller
        self._input_queue = input_queue
        self._ser_data_pin = ser_data_pin
        self._ser_clk_pin = ser_clk_pin
        self._ser_latch_pin = ser_latch_pin
        self._n = reg_len
        self._lock = lock
        self._stop_event = stop_event
        self._event_queue = event_queue

    def _work_shift(self, value: Any) -> None:
        """
        Записать значение в сдвиговый регистр (MSB-first).

        Вызывается уже под захваченным ``self._lock`` (внешним),
        поэтому использует ``write_pin_nolock`` — без лишнего внутреннего
        захвата. Это убирает ~48 лишних Lock.__enter__ на одну передачу
        16-битного слова.

        Для каждого бита (от старшего к младшему):
          1. Установить SER_DATA = бит.
          2. Импульс CLK: 0 → 1 → 0.
        После всех битов — импульс LATCH: 0 → 1 → 0.

        Parameters
        ----------
        value : int
            Число для записи. Используются ``reg_len`` младших бит.
        """
        wp = self._controller.write_pin_nolock
        for i in range(self._n - 1, -1, -1):
            bit = (value >> i) & 1
            wp(self._ser_data_pin, bit)
            wp(self._ser_clk_pin, 0)
            wp(self._ser_clk_pin, 1)
            wp(self._ser_clk_pin, 0)
        # Защёлка: передаём накопленные данные на выходы регистра
        wp(self._ser_latch_pin, 0)
        wp(self._ser_latch_pin, 1)
        wp(self._ser_latch_pin, 0)

    def run(self) -> None:
        """
        Основной цикл потока сдвигового регистра.

        Блокируется на очереди, при получении сообщения записывает
        значение в регистр под локом. Завершается при установке
        ``stop_event`` (очередь будет разблокирована по timeout).
        """
        logger.info(
            "⚡ ShiftRegWorker запущен (DATA=%s CLK=%s LATCH=%s bits=%d)",
            self._ser_data_pin, self._ser_clk_pin, self._ser_latch_pin, self._n,
        )
        while not self._stop_event.is_set():
            try:
                # Ждём сообщение с таймаутом, чтобы проверять stop_event
                msg = self._input_queue.get(timeout=0.1)
                if msg is None:
                    # None используется как sentinel для остановки
                    continue
                with self._lock:
                    self._work_shift(msg)
                if self._event_queue is not None:
                    try:
                        self._event_queue.put_nowait(
                            ScudEvent(
                                type=EventType.SHIFT_DONE,
                                source=EventSource.SHIFT,
                                payload={"value": msg, "bits": self._n},
                            )
                        )
                    except Full:
                        pass
            except Empty:
                # Таймаут — проверяем stop_event и ждём дальше
                continue
            except Exception as e:
                logger.error("ShiftRegWorker ошибка: %s", e, exc_info=True)
        logger.info("ShiftRegWorker остановлен.")
