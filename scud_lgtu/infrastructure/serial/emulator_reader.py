"""
Эмулятор Serial Reader для работы без аппаратного обеспечения.

Читает данные из консоли (stdin) вместо реального серийного порта.
Полностью совместим по API с BackgroundSerialReader.
"""
import threading
import logging
import time
import sys
from queue import Queue
from typing import Optional

logger = logging.getLogger(__name__)


class EmulatorSerialReader:
    """
    Эмулятор Serial Reader.

    Читает строки из консоли (stdin) вместо реального серийного порта.
    Полностью совместим по API с BackgroundSerialReader.
    """

    def __init__(
        self,
        port: str = "/dev/ttyUSB0",
        baudrate: int = 115200,
        timeout: float = 0.05,
        retry_delay: float = 1.0,
    ):
        """
        Инициализировать эмулятор reader.

        Parameters
        ----------
        port : str
            Путь к устройству (например, '/dev/ttyUSB0')
        baudrate : int
            Скорость порта (игнорируется в эмуляции)
        timeout : float
            Таймаут чтения одной строки (с)
        retry_delay : float
            Задержка перед повторной попыткой при ошибке (с)
        """
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.retry_delay = retry_delay

        # Очередь строк, прочитанных из консоли
        self.queue: Queue = Queue()

        # Объекты синхронизации
        self._running = threading.Event()
        self._thread: Optional[threading.Thread] = None

        logger.info(f"[EmulatorSerialReader] Initialized for port {port} (console input mode)")

    def _read_loop(self) -> None:
        """
        Рабочий цикл потока.

        Читает строки из stdin и кладёт их в очередь.
        """
        logger.info(f"[EmulatorSerialReader] Запуск потока для порта {self.port} (читаем из консоли)")
        print(f"\n[EmulatorSerialReader] Чтение из консоли для {self.port}")
        print(f"[EmulatorSerialReader] Введите данные (например, QR-код) и нажмите Enter:")
        print(f"[EmulatorSerialReader] Для остановки нажмите Ctrl+C или введите 'quit'\n")

        try:
            while self._running.is_set():
                try:
                    # Читаем строку из консоли с таймаутом
                    line = input().strip()

                    if line.lower() == 'quit':
                        logger.info(f"[EmulatorSerialReader] Получена команда 'quit', остановка")
                        break

                    if line:
                        logger.info(f"[EmulatorSerialReader] {self.port} ← {line}")
                        self.queue.put(line)
                        print(f"[EmulatorSerialReader] Принято: {line}\n")

                except EOFError:
                    logger.warning(f"[EmulatorSerialReader] EOF (Ctrl+D), остановка")
                    break
                except KeyboardInterrupt:
                    logger.info(f"[EmulatorSerialReader] KeyboardInterrupt, остановка")
                    break
                except Exception as e:
                    logger.warning(f"[EmulatorSerialReader] Ошибка чтения: {e}")
                    time.sleep(self.retry_delay)
        finally:
            logger.info(f"[EmulatorSerialReader] Поток {self.port} завершён")

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
            logger.warning(f"[EmulatorSerialReader] Поток {self.port} уже запущен")
            return self.queue

        self._running.set()
        self._thread = threading.Thread(
            target=self._read_loop,
            name=f"EmulatorSerialReader-{self.port}",
            daemon=True,
        )
        self._thread.start()
        logger.info(f"[EmulatorSerialReader] Поток запущен для {self.port}")
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
            logger.info(f"[EmulatorSerialReader] Поток {self.port} не запущен")
            return

        self._running.clear()
        self._thread.join(timeout=timeout)

        if self._thread.is_alive():
            logger.warning(
                f"[EmulatorSerialReader] Поток {self.port} не завершился за {timeout}s"
            )
        else:
            logger.info(f"[EmulatorSerialReader] Поток {self.port} остановлен")

    def is_alive(self) -> bool:
        """Жив ли фоновый поток чтения порта."""
        return self._thread is not None and self._thread.is_alive()


class EmulatorSerialReaderWithQueue:
    """
    Эмулятор Serial Reader с возможностью программного добавления данных.

    Читает данные из очереди вместо консоли для автоматического тестирования.
    """

    def __init__(
        self,
        port: str = "/dev/ttyUSB0",
        baudrate: int = 115200,
        timeout: float = 0.05,
        retry_delay: float = 1.0,
    ):
        """
        Инициализировать эмулятор reader с очередью.

        Parameters
        ----------
        port : str
            Путь к устройству
        baudrate : int
            Скорость порта (игнорируется)
        timeout : float
            Таймаут чтения
        retry_delay : float
            Задержка перед повторной попыткой
        """
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.retry_delay = retry_delay

        # Очередь строк, прочитанных из порта
        self.queue: Queue = Queue()

        # Внутренняя очередь для симуляции входящих данных
        self._input_queue: Queue = Queue()

        # Объекты синхронизации
        self._running = threading.Event()
        self._thread: Optional[threading.Thread] = None

        logger.info(f"[EmulatorSerialReaderWithQueue] Initialized for port {port} (queue input mode)")

    def _read_loop(self) -> None:
        """Рабочий цикл потока (читает из внутренней очереди)."""
        logger.info(f"[EmulatorSerialReaderWithQueue] Запуск потока для порта {self.port}")

        try:
            while self._running.is_set():
                try:
                    # Читаем из внутренней очереди с таймаутом
                    line = self._input_queue.get(timeout=0.1)

                    if line:
                        logger.info(f"[EmulatorSerialReaderWithQueue] {self.port} ← {line}")
                        self.queue.put(line)

                except:
                    # Таймаут - продолжаем
                    time.sleep(0.01)
        finally:
            logger.info(f"[EmulatorSerialReaderWithQueue] Поток {self.port} завершён")

    def start(self) -> Queue:
        """Запустить фоновый поток чтения."""
        if self._thread is not None and self._thread.is_alive():
            logger.warning(f"[EmulatorSerialReaderWithQueue] Поток {self.port} уже запущен")
            return self.queue

        self._running.set()
        self._thread = threading.Thread(
            target=self._read_loop,
            name=f"EmulatorSerialReaderWithQueue-{self.port}",
            daemon=True,
        )
        self._thread.start()
        logger.info(f"[EmulatorSerialReaderWithQueue] Поток запущен для {self.port}")
        return self.queue

    def stop(self, timeout: float = 5.0) -> None:
        """Остановить фоновый поток."""
        if self._thread is None or not self._thread.is_alive():
            logger.info(f"[EmulatorSerialReaderWithQueue] Поток {self.port} не запущен")
            return

        self._running.clear()
        self._thread.join(timeout=timeout)

        if self._thread.is_alive():
            logger.warning(f"[EmulatorSerialReaderWithQueue] Поток {self.port} не завершился за {timeout}s")
        else:
            logger.info(f"[EmulatorSerialReaderWithQueue] Поток {self.port} остановлен")

    def is_alive(self) -> bool:
        """Жив ли фоновый поток."""
        return self._thread is not None and self._thread.is_alive()

    def add_input_line(self, line: str):
        """
        Добавить строку для симуляции входящих данных.

        Parameters
        ----------
        line : str
            Строка для добавления
        """
        self._input_queue.put(line)
        logger.debug(f"[EmulatorSerialReaderWithQueue] Added input line: {line}")

    def add_input_lines(self, lines: list):
        """
        Добавить несколько строк для симуляции.

        Parameters
        ----------
        lines : list
            Список строк
        """
        for line in lines:
            self.add_input_line(line)
        logger.debug(f"[EmulatorSerialReaderWithQueue] Added {len(lines)} input lines")
