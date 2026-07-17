"""
Mock Serial Port для тестирования без аппаратного обеспечения.

Эмулирует поведение serial.Serial для запуска тестов на любой машине.
"""
import threading
import logging
import time
from queue import Queue
from typing import Optional, List

logger = logging.getLogger(__name__)


class MockSerial:
    """
    Mock serial.Serial для тестирования.

    Эмулирует поведение serial.Serial без реального порта.
    Позволяет симулировать приём данных из порта.
    """

    def __init__(
        self,
        port: str = "/dev/ttyUSB0",
        baudrate: int = 115200,
        timeout: float = 0.05,
        write_timeout: Optional[float] = None,
    ):
        """
        Инициализировать mock serial порт.

        Parameters
        ----------
        port : str
            Путь к устройству (например, '/dev/ttyUSB0')
        baudrate : int
            Скорость передачи данных
        timeout : float
            Таймаут чтения в секундах
        write_timeout : float, optional
            Таймаут записи
        """
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.write_timeout = write_timeout

        self._is_open = False
        self._input_queue: Queue = Queue()  # Очередь входящих данных
        self._output_data: List[bytes] = []  # Записанные данные
        self._lock = threading.Lock()

        # Для отслеживания вызовов
        self.write_calls: List[bytes] = []
        self.readline_calls: int = 0

    def open(self):
        """Открыть порт (mock)."""
        with self._lock:
            self._is_open = True
            logger.info(f"[MockSerial] Port {self.port} opened")

    def close(self):
        """Закрыть порт (mock)."""
        with self._lock:
            self._is_open = False
            self._input_queue.queue.clear()
            self._output_data.clear()
            logger.info(f"[MockSerial] Port {self.port} closed")

    @property
    def is_open(self) -> bool:
        """Открыт ли порт."""
        return self._is_open

    def write(self, data: bytes) -> int:
        """
        Записать данные в порт.

        Parameters
        ----------
        data : bytes
            Данные для записи

        Returns
        -------
        int
            Количество записанных байт
        """
        with self._lock:
            if not self._is_open:
                raise Exception("Port is not open")
            self._output_data.append(data)
            self.write_calls.append(data)
            logger.debug(f"[MockSerial] Written {len(data)} bytes: {data[:50]}")
            return len(data)

    def readline(self) -> bytes:
        """
        Прочитать строку из порта (до newline).

        Returns
        -------
        bytes
            Прочитанные данные
        """
        with self._lock:
            if not self._is_open:
                raise Exception("Port is not open")

            self.readline_calls += 1

            # Если в очереди есть данные, возвращаем их
            if not self._input_queue.empty():
                data = self._input_queue.get()
                logger.debug(f"[MockSerial] Read line: {data[:50]}")
                return data

            # Иначе возвращаем пустые данные (таймаут)
            logger.debug(f"[MockSerial] Readline timeout (no data)")
            return b""

    def read(self, size: int = 1) -> bytes:
        """
        Прочитать указанное количество байт.

        Parameters
        ----------
        size : int
            Количество байт для чтения

        Returns
        -------
        bytes
            Прочитанные данные
        """
        with self._lock:
            if not self._is_open:
                raise Exception("Port is not open")

            # Если в очереди есть данные, возвращаем их
            if not self._input_queue.empty():
                data = self._input_queue.get()
                return data[:size]

            return b""

    def flush(self):
        """Сбросить буферы (mock)."""
        with self._lock:
            self._output_data.clear()
            logger.debug("[MockSerial] Flush")

    def reset_input_buffer(self):
        """Сбросить входной буфер (mock)."""
        with self._lock:
            self._input_queue.queue.clear()
            logger.debug("[MockSerial] Reset input buffer")

    def reset_output_buffer(self):
        """Сбросить выходной буфер (mock)."""
        with self._lock:
            self._output_data.clear()
            logger.debug("[MockSerial] Reset output buffer")

    def in_waiting(self) -> int:
        """
        Количество байт в буфере (mock).

        Returns
        -------
        int
            Количество байт
        """
        with self._lock:
            return self._input_queue.qsize()

    def simulate_input(self, data: bytes):
        """
        Симулировать входящие данные (для тестов).

        Parameters
        ----------
        data : bytes
            Данные для добавления в очередь
        """
        with self._lock:
            self._input_queue.put(data)
            logger.info(f"[MockSerial] Simulated input: {data[:50]}")

    def simulate_input_line(self, line: str):
        """
        Симулировать входящую строку (для тестов).

        Parameters
        ----------
        line : str
            Строка для добавления в очередь
        """
        self.simulate_input(line.encode("utf-8"))

    def get_output_data(self) -> List[bytes]:
        """
        Получить записанные данные (для тестов).

        Returns
        -------
        list
            Список записанных данных
        """
        with self._lock:
            return self._output_data.copy()

    def get_state(self) -> dict:
        """
        Получить состояние порта (для тестов).

        Returns
        -------
        dict
            Состояние порта
        """
        with self._lock:
            return {
                "is_open": self._is_open,
                "port": self.port,
                "baudrate": self.baudrate,
                "timeout": self.timeout,
                "input_queue_size": self._input_queue.qsize(),
                "output_data_count": len(self._output_data),
                "write_calls_count": len(self.write_calls),
                "readline_calls_count": self.readline_calls,
            }

    def reset(self):
        """Сбросить состояние порта (для тестов)."""
        with self._lock:
            self._input_queue.queue.clear()
            self._output_data.clear()
            self.write_calls.clear()
            self.readline_calls = 0
            logger.info("[MockSerial] Port reset")


class MockBackgroundSerialReader:
    """
    Mock BackgroundSerialReader для тестирования.

    Эмулирует поведение BackgroundSerialReader без реального порта.
    """

    def __init__(
        self,
        port: str = "/dev/ttyUSB0",
        baudrate: int = 115200,
        timeout: float = 0.05,
        retry_delay: float = 1.0,
    ):
        """
        Инициализировать mock reader.

        Parameters
        ----------
        port : str
            Путь к устройству
        baudrate : int
            Скорость порта
        timeout : float
            Таймаут чтения
        retry_delay : float
            Задержка перед повторной попыткой
        """
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.retry_delay = retry_delay

        self.queue: Queue = Queue()
        self._running = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._mock_serial = MockSerial(port, baudrate, timeout)

        # Для симуляции входящих данных
        self._input_lines: List[str] = []
        self._input_index = 0

    def _read_loop(self) -> None:
        """Рабочий цикл потока (mock)."""
        logger.info(f"[MockBackgroundSerialReader] Запуск потока для порта {self.port}")

        try:
            self._mock_serial.open()

            while self._running.is_set():
                try:
                    # Симулируем чтение из очереди входящих данных
                    if self._input_index < len(self._input_lines):
                        line = self._input_lines[self._input_index]
                        self._input_index += 1
                        logger.debug(f"[MockBackgroundSerialReader] {self.port} → {line}")
                        self.queue.put(line)
                        time.sleep(0.01)  # Небольшая задержка
                    else:
                        time.sleep(0.01)  # Нет данных - ждём

                except Exception as e:
                    logger.warning(f"[MockBackgroundSerialReader] Ошибка: {e}")
                    time.sleep(self.retry_delay)
        finally:
            self._mock_serial.close()
            logger.info(f"[MockBackgroundSerialReader] Порт {self.port} закрыт, поток завершён")

    def start(self) -> Queue:
        """
        Запустить фоновый поток чтения.

        Returns
        -------
        queue.Queue
            Очередь прочитанных строк
        """
        if self._thread is not None and self._thread.is_alive():
            logger.warning(f"[MockBackgroundSerialReader] Поток {self.port} уже запущен")
            return self.queue

        self._running.set()
        self._thread = threading.Thread(
            target=self._read_loop,
            name=f"MockSerialReader-{self.port}",
            daemon=True,
        )
        self._thread.start()
        logger.info(f"[MockBackgroundSerialReader] Поток запущен для {self.port}")
        return self.queue

    def stop(self, timeout: float = 5.0) -> None:
        """
        Остановить фоновый поток.

        Parameters
        ----------
        timeout : float
            Максимальное время ожидания
        """
        if self._thread is None or not self._thread.is_alive():
            logger.info(f"[MockBackgroundSerialReader] Поток {self.port} не запущен")
            return

        self._running.clear()
        self._thread.join(timeout=timeout)

        if self._thread.is_alive():
            logger.warning(f"[MockBackgroundSerialReader] Поток {self.port} не завершился за {timeout}s")
        else:
            logger.info(f"[MockBackgroundSerialReader] Поток {self.port} остановлен")

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
        self._input_lines.append(line)
        logger.debug(f"[MockBackgroundSerialReader] Added input line: {line}")

    def add_input_lines(self, lines: List[str]):
        """
        Добавить несколько строк для симуляции.

        Parameters
        ----------
        lines : list
            Список строк
        """
        self._input_lines.extend(lines)
        logger.debug(f"[MockBackgroundSerialReader] Added {len(lines)} input lines")

    def reset(self):
        """Сбросить состояние reader."""
        self._input_lines.clear()
        self._input_index = 0
        self.queue.queue.clear()
        logger.info("[MockBackgroundSerialReader] Reader reset")

    def get_state(self) -> dict:
        """
        Получить состояние reader (для тестов).

        Returns
        -------
        dict
            Состояние reader
        """
        return {
            "port": self.port,
            "baudrate": self.baudrate,
            "timeout": self.timeout,
            "is_alive": self.is_alive(),
            "input_lines_count": len(self._input_lines),
            "input_index": self._input_index,
            "queue_size": self.queue.qsize(),
            "readline_calls_count": self._mock_serial.readline_calls,
        }
