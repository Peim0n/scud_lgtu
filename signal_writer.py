"""
Поток управления выходными GPIO-сигналами (OutputSignalWriter).

Полная замена оригинального ``signal_writer.OutputSignalWriter`` с переходом
с ``multiprocessing.Process`` на ``threading.Thread``.

Что делает этот модуль
----------------------
Принимает команды ``OutputCommand`` из очереди и управляет выходными
GPIO-линиями. Поддерживает:
  * немедленное включение/выключение;
  * автоматическое выключение через заданное время (``duration > 0``).

Формат команды
--------------
``OutputCommand(output_id, duration, value)``

  * ``output_id`` — логический идентификатор выхода.
  * ``duration`` — если > 0, через столько секунд выход отключится автоматически.
  * ``value`` — ``Value.ACTIVE`` (по умолчанию) или ``Value.INACTIVE``.

Использование
-------------
::

    from signal_writer import OutputSignalWriter, OutputCommand
    from gpiod.line import Value

    OUTPUTS = {0: 14, 1: 16}
    t, q, ev = OutputSignalWriter.start(OUTPUTS)

    q.put(OutputCommand(output_id=0, duration=1.5))   # включить на 1.5 с
    q.put(OutputCommand(output_id=1, duration=0, value=Value.ACTIVE))   # включить навсегда
    q.put(OutputCommand(output_id=1, duration=0, value=Value.INACTIVE)) # выключить

    ev.clear()
    t.join(timeout=2)
"""

import threading
import logging
import time
from dataclasses import dataclass, field
from queue import Queue, Empty
from typing import Optional, Dict

import gpiod
from gpiod.line import Value

logger = logging.getLogger(__name__)


@dataclass
class OutputCommand:
    """Команда управления одним выходным пином."""
    output_id: int
    """Логический ID выхода (ключ из output_offsets)."""
    duration: float
    """Длительность включения (с). 0 — без автовыключения."""
    value: Value = field(default=Value.ACTIVE)
    """Целевое состояние линии."""


class OutputSignalWriter:
    """
    Поток управления выходными GPIO-линиями.

    Parameters
    ----------
    chip_path : str
        Путь к GPIO chip, например ``'/dev/gpiochip0'``.
    output_offsets : dict
        ``{logical_id: gpio_offset}`` — маппинг выходов на GPIO-линии.
    input_queue : queue.Queue
        Очередь входящих команд ``OutputCommand``.
    running_event : threading.Event, optional
        Событие работы. Если None — создаётся и устанавливается автоматически.
    """

    def __init__(
        self,
        chip_path: str = "/dev/gpiochip0",
        output_offsets: Optional[Dict[int, int]] = None,
        input_queue: Optional[Queue] = None,
        running_event: Optional[threading.Event] = None,
    ):
        """Инициализировать маппинг выходов и очередь команд."""
        self.chip_path = chip_path
        self.output_offsets: Dict[int, int] = output_offsets or {}
        self.input_queue = input_queue or Queue()
        self.running = running_event if running_event else threading.Event()

        # Таймер автовыключения: gpio_offset → время выключения (Unix timestamp)
        self._scheduled_offs: Dict[int, float] = {}
        self._request: Optional[gpiod.LineRequest] = None

    def open(self) -> None:
        """
        Захватить GPIO-линии в режиме OUTPUT (начальное состояние INACTIVE).

        Raises
        ------
        OSError
            Если не удаётся получить доступ к линиям.
        """
        config = {
            offset: gpiod.LineSettings(
                direction=gpiod.line.Direction.OUTPUT,
                output_value=Value.INACTIVE,
            )
            for offset in self.output_offsets.values()
        }
        try:
            self._request = gpiod.request_lines(
                self.chip_path,
                consumer="scud-outputs",
                config=config,
            )
            logger.info(
                "[OutputSignalWriter] ✓ Линии %s захвачены.",
                list(self.output_offsets.values()),
            )
        except OSError as e:
            logger.error("[OutputSignalWriter] ✗ Ошибка открытия GPIO: %s", e)
            raise

    def run(self) -> None:
        """
        Основной цикл потока.

        Используется как ``target`` для ``threading.Thread``.
        Читает команды из очереди, применяет их к GPIO и обрабатывает
        таймеры автовыключения.
        """
        try:
            self.open()
            while self.running.is_set():
                # Читаем команду с таймаутом 10 мс (чтобы регулярно проверять таймеры)
                try:
                    cmd: OutputCommand = self.input_queue.get(timeout=0.01)
                    offset = self.output_offsets.get(cmd.output_id)
                    if offset is not None:
                        # Если устанавливаем ACTIVE — отменяем прежний таймер выключения
                        if cmd.value == Value.ACTIVE:
                            self._scheduled_offs.pop(offset, None)

                        self._request.set_value(offset, cmd.value)

                        if cmd.duration > 0:
                            # Планируем автовыключение через duration секунд
                            self._scheduled_offs[offset] = time.time() + cmd.duration
                        elif cmd.value == Value.ACTIVE:
                            # duration == 0 и ACTIVE: немедленное выключение (одиночный импульс)
                            self._request.set_value(offset, Value.INACTIVE)

                except Empty:
                    pass  # Нет команды — проверяем таймеры

                # Обработка таймеров автовыключения
                now = time.time()
                for offset, off_time in list(self._scheduled_offs.items()):
                    if now >= off_time:
                        self._request.set_value(offset, Value.INACTIVE)
                        del self._scheduled_offs[offset]
                        logger.debug("[OutputSignalWriter] offset=%d выключен по таймеру.", offset)

        except Exception as e:
            logger.error("[OutputSignalWriter] Критическая ошибка: %s", e, exc_info=True)
        finally:
            # Безопасно выключаем все выходы при завершении
            if self._request is not None:
                for offset in self.output_offsets.values():
                    try:
                        self._request.set_value(offset, Value.INACTIVE)
                    except Exception:
                        pass
                self._request.release()
                logger.info("[OutputSignalWriter] Линии освобождены.")
            logger.info("[OutputSignalWriter] Поток завершён.")

    @classmethod
    def start(cls, output_offsets: Dict[int, int], chip_path: str = "/dev/gpiochip0"):
        """
        Создать экземпляр и запустить фоновый поток.

        Parameters
        ----------
        output_offsets : dict
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
        writer = cls(chip_path=chip_path, output_offsets=output_offsets,
                     input_queue=q, running_event=ev)
        t = threading.Thread(target=writer.run, name="OutputSignalWriter", daemon=True)
        t.start()
        return t, q, ev
