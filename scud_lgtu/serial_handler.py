"""
Обработчик последовательного порта и выходных сигналов (SerialHandler).

Объединяет BackgroundSerialReader и OutputSignalWriter в один модуль.

BackgroundSerialReader:
- Читает строки из последовательного порта в фоновом потоке
- Переход с multiprocessing.Process на threading.Thread

OutputSignalWriter:
- Управляет выходными GPIO-линиями
- Поддерживает автоматическое выключение через заданное время
- Переход с multiprocessing.Process на threading.Thread
"""

import threading
import logging
import time
from queue import Queue, Empty
from dataclasses import dataclass, field
from typing import Optional, Dict

import serial
import gpiod
from gpiod.line import Value

logger = logging.getLogger(__name__)


# ============================================================================
# BackgroundSerialReader
# ============================================================================

class BackgroundSerialReader:
    """
    Читает строки из последовательного порта в фоновом потоке.

    Parameters
    ----------
    port : str
        Путь к устройству, например ``'/dev/ttyS1'``.
    baudrate : int
        Скорость порта.
    timeout : float
        Таймаут чтения одной строки (с). Влияет на отзывчивость
        при ошибках.
    retry_delay : float
        Задержка перед повторной попыткой при ошибке (с).

    Attributes
    ----------
    queue : queue.Queue
        Публичная очередь принятых строк.
    """

    def __init__(self, port: str = "/dev/ttyUSB0", baudrate: int = 19200, timeout: float = 0.05, retry_delay: float = 1.0):
        """Инициализировать параметры Serial-порта."""
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.retry_delay = retry_delay

        # Очередь строк, прочитанных из порта
        self.queue: Queue = Queue()

        # Объекты синхронизации
        self._running = threading.Event()
        self._thread: threading.Thread | None = None

    def _read_loop(self) -> None:
        """
        Рабочий цикл потока.

        Открывает порт, читает строки (по newline) и кладёт их в очередь.
        При ошибке чтения ждёт 1 с и продолжает.
        Завершается при сбросе ``_running``.
        """
        logger.info("[BackgroundSerialReader] Запуск потока для порта %s…", self.port)

        try:
            ser = serial.Serial(self.port, self.baudrate, timeout=self.timeout)
            logger.info("[BackgroundSerialReader] Порт %s открыт.", self.port)
        except serial.SerialException as e:
            logger.error("[BackgroundSerialReader] Ошибка открытия %s: %s", self.port, e)
            return
        except Exception as e:
            logger.error("[BackgroundSerialReader] Неизвестная ошибка открытия %s: %s", self.port, e)
            return

        try:
            while self._running.is_set():
                try:
                    # readline() блокируется не дольше self.timeout секунд
                    line = ser.readline().decode("utf-8", errors="ignore").strip()
                    if line:
                        logger.debug("[BackgroundSerialReader] %s → %r", self.port, line)
                        self.queue.put(line)
                except serial.SerialException as e:
                    logger.warning("[BackgroundSerialReader] Ошибка чтения: %s", e)
                    time.sleep(self.retry_delay)
                except Exception as e:
                    logger.warning("[BackgroundSerialReader] Неожиданная ошибка: %s", e)
                    time.sleep(self.retry_delay)
        finally:
            if ser.is_open:
                ser.close()
            logger.info("[BackgroundSerialReader] Порт %s закрыт, поток завершён.", self.port)

    def start(self) -> Queue:
        """
        Запустить фоновый поток чтения.

        Если поток уже запущен — возвращает существующую очередь.

        Returns
        -------
        queue.Queue
            Очередь, в которую поступают прочитанные строки.
        """
        if self._thread is not None and self._thread.is_alive():
            logger.warning("[BackgroundSerialReader] Поток %s уже запущен.", self.port)
            return self.queue

        self._running.set()
        self._thread = threading.Thread(
            target=self._read_loop,
            name=f"SerialReader-{self.port}",
            daemon=True,  # Завершается вместе с основным процессом
        )
        self._thread.start()
        logger.info("[BackgroundSerialReader] Поток запущен для %s.", self.port)
        return self.queue

    def stop(self, timeout: float = 5.0) -> None:
        """
        Остановить фоновый поток.

        Сбрасывает флаг ``_running`` и ждёт завершения потока.

        Parameters
        ----------
        timeout : float
            Максимальное время ожидания (с).
        """
        if self._thread is None or not self._thread.is_alive():
            logger.info("[BackgroundSerialReader] Поток %s не запущен.", self.port)
            return

        self._running.clear()
        self._thread.join(timeout=timeout)

        if self._thread.is_alive():
            logger.warning(
                "[BackgroundSerialReader] Поток %s не завершился за %ss.", self.port, timeout
            )
        else:
            logger.info("[BackgroundSerialReader] Поток %s остановлен.", self.port)

    def is_alive(self) -> bool:
        """Жив ли фоновый поток чтения порта."""
        return self._thread is not None and self._thread.is_alive()


# ============================================================================
# OutputSignalWriter
# ============================================================================

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
