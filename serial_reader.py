"""
Фоновый поток чтения последовательного порта (BackgroundSerialReader).

Полная замена оригинального ``serial_reader.BackgroundSerialReader`` с
переходом с ``multiprocessing.Process`` на ``threading.Thread``.

Преимущества threading для последовательного порта
---------------------------------------------------
* Нет накладных расходов на fork/pickle.
* Очередь ``queue.Queue`` эффективнее ``multiprocessing.Queue``.
* Serial-объект передаётся в поток напрямую, без сериализации.

Использование
-------------
::

    reader = BackgroundSerialReader('/dev/ttyS1', baud=19200)
    q = reader.start()
    try:
        while True:
            msg = q.get(timeout=1)
            print(msg)
    except KeyboardInterrupt:
        pass
    finally:
        reader.stop()
"""

import threading
import logging
import time
from queue import Queue

import serial

logger = logging.getLogger(__name__)


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
        при остановке потока (``stop()``).

    Attributes
    ----------
    queue : queue.Queue
        Публичная очередь принятых строк.
    """

    def __init__(self, port: str = "/dev/ttyUSB0", baudrate: int = 19200, timeout: float = 0.05):
        """Инициализировать параметры Serial-порта."""
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout

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
                    time.sleep(1)
                except Exception as e:
                    logger.warning("[BackgroundSerialReader] Неожиданная ошибка: %s", e)
                    time.sleep(1)
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
