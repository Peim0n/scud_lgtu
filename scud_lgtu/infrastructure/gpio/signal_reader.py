"""
Поток чтения GPIO-сигналов (InputSignalReader).

Полная замена оригинального ``signal_reader.InputSignalReader`` с переходом
с ``multiprocessing.Process`` на ``threading.Thread``.

Что делает этот модуль
----------------------
Ожидает нарастающий (RISING) и спадающий (FALLING) фронт на нескольких
GPIO-линиях. Измеряет длительность HIGH-импульсов и кладёт ``InputData``
в выходную очередь.

Использование
-------------
::

    from signal_reader import InputSignalReader, InputData

    SENSORS = {0: 19, 1: 18}  # {logical_id: gpio_offset}
    t, q, ev = InputSignalReader.start(SENSORS)

    try:
        while True:
            data: InputData = q.get(timeout=0.1)  # Таймаут 100 мс для проверки running_event
            print(f"Датчик {data.sensor_id}, длительность {data.duration:.3f}с")
    except KeyboardInterrupt:
        pass
    finally:
        ev.clear()
        t.join(timeout=0.5)  # Таймаут 500 мс для завершения потока
"""

import threading
import logging
import time
import datetime
from dataclasses import dataclass
from queue import Queue
from typing import Optional, Dict

import gpiod
from gpiod.line import Edge, Bias

logger = logging.getLogger(__name__)


@dataclass
class InputData:
    """Результат измерения длительности импульса."""
    sensor_id: int
    """Логический идентификатор датчика."""
    duration: float
    """Длительность HIGH-импульса (секунды)."""
    start_time: float
    """Время начала импульса (Unix timestamp)."""
    end_time: float
    """Время конца импульса (Unix timestamp)."""


class InputSignalReader:
    """
    Поток чтения длительности импульсов на GPIO-линиях.

    Логика измерения
    ----------------
    * RISING (или LOW→HIGH): запомнить время начала в ``active_pulses[offset]``.
    * FALLING (или HIGH→LOW): вычислить длительность = end - start, отправить в очередь.
    * Первые N мс после старта игнорируются (подавление дребезга при инициализации).

    Parameters
    ----------
    chip_path : str
        Путь к GPIO chip, например ``'/dev/gpiochip0'``.
    sensor_offsets : dict
        ``{logical_id: gpio_offset}`` — маппинг датчиков на GPIO-линии.
    output_queue : queue.Queue
        Очередь для передачи ``InputData`` в главный поток.
    running_event : threading.Event, optional
    debounce_time : float, optional
        Время подавления дребезга при инициализации (с). По умолчанию 0.5 с.
    event_timeout : float, optional
        Таймаут ожидания событий (с). По умолчанию 0.1 с.
        Событие работы. Если None — создаётся и устанавливается автоматически.
    """

    def __init__(
        self,
        chip_path: str = "/dev/gpiochip0",
        sensor_offsets: Optional[Dict[int, int]] = None,
        output_queue: Optional[Queue] = None,
        running_event: Optional[threading.Event] = None,
        debounce_time: float = 0.5,
        event_timeout: float = 0.1,
    ):
        """Инициализировать маппинг датчиков и очередь результатов."""
        self.chip_path = chip_path
        self.sensor_offsets = sensor_offsets or {}
        # Обратный маппинг: gpio_offset → logical_id
        self._gpio_to_id: Dict[int, int] = {v: k for k, v in self.sensor_offsets.items()}
        self.output_queue = output_queue
        self.running = running_event if running_event else threading.Event()
        self._debounce_time = debounce_time
        self._event_timeout = event_timeout

        # Текущие незакрытые импульсы: gpio_offset → time начала
        self._active_pulses: Dict[int, float] = {}
        self._request: Optional[gpiod.LineRequest] = None

    def open(self) -> None:
        """
        Захватить GPIO-линии с детекцией обоих фронтов и pull-up.

        Raises
        ------
        OSError
            Если не удаётся получить доступ к линиям.
        """
        config = {
            offset: gpiod.LineSettings(
                direction=gpiod.line.Direction.INPUT,
                edge_detection=Edge.BOTH,
                bias=Bias.PULL_UP,
            )
            for offset in self.sensor_offsets.values()
        }
        try:
            self._request = gpiod.request_lines(
                self.chip_path,
                consumer="scud-sensors",
                config=config,
            )
            logger.info(
                "[InputSignalReader] ✓ Линии %s захвачены.",
                list(self.sensor_offsets.values()),
            )
        except OSError as e:
            logger.error("[InputSignalReader] ✗ Ошибка открытия GPIO: %s", e)
            raise

    def run(self) -> None:
        """
        Основной цикл потока.

        Используется как ``target`` для ``threading.Thread``.
        Ожидает события gpiod (RISING/FALLING), измеряет длительность
        импульсов и помещает результаты в ``output_queue``.
        """
        try:
            self.open()
            startup_time = time.time()

            while self.running.is_set():
                # Ждём события не дольше configured timeout, чтобы проверять running_event
                if self._request.wait_edge_events(datetime.timedelta(seconds=self._event_timeout)):
                    for event in self._request.read_edge_events():
                        # Игнорируем события в первые N мс (шум при инициализации)
                        if time.time() - startup_time < self._debounce_time:
                            continue

                        # Время события в секундах (timestamp_ns — аппаратный таймер)
                        event_time = event.timestamp_ns / 1_000_000_000.0
                        offset = event.line_offset
                        sensor_id = self._gpio_to_id.get(offset)
                        if sensor_id is None:
                            continue

                        event_name = str(event.event_type)
                        if "RISING" in event_name:
                            # Начало импульса
                            self._active_pulses[offset] = event_time
                        elif "FALLING" in event_name:
                            # Конец импульса — вычисляем длительность
                            start = self._active_pulses.pop(offset, None)
                            if start is not None:
                                duration = event_time - start
                                data = InputData(
                                    sensor_id=sensor_id,
                                    duration=duration,
                                    start_time=start,
                                    end_time=event_time,
                                )
                                if self.output_queue is not None:
                                    self.output_queue.put(data)
                                logger.debug(
                                    "[InputSignalReader] Датчик %d: %.3f с",
                                    sensor_id, duration,
                                )
        except Exception as e:
            if self.running.is_set():
                logger.error("[InputSignalReader] Критическая ошибка: %s", e, exc_info=True)
        finally:
            if self._request is not None:
                self._request.release()
                logger.info("[InputSignalReader] Линии освобождены.")
            logger.info("[InputSignalReader] Поток завершён.")

    @classmethod
    def start(cls, sensor_offsets: Dict[int, int], chip_path: str = "/dev/gpiochip0"):
        """
        Создать экземпляр и запустить фоновый поток.

        Parameters
        ----------
        sensor_offsets : dict
            ``{logical_id: gpio_offset}``
        chip_path : str
            Путь к GPIO chip.

        Returns
        -------
        tuple
            ``(thread, queue, event)``
        """
        q: Queue = Queue()
        ev = threading.Event()
        ev.set()
        reader = cls(chip_path=chip_path, sensor_offsets=sensor_offsets,
                     output_queue=q, running_event=ev)
        t = threading.Thread(target=reader.run, name="InputSignalReader", daemon=True)
        t.start()
        return t, q, ev
