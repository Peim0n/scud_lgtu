"""Мок serial пакета app.tests.mocks."""
import queue


class MockSerialPort:
    """Мок serial-порта, имитирующий поведение pyserial."""

    def __init__(self, port: str = "/dev/ttyUSB0", baudrate: int = 9600, timeout: float = 1.0):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self._is_open = False
        self._read_queue = queue.Queue()
        self._write_queue = queue.Queue()

    def open(self) -> None:
        """Открыть serial-порт."""
        self._is_open = True

    def close(self) -> None:
        """Закрыть serial-порт."""
        self._is_open = False

    def is_open(self) -> bool:
        """Проверить, открыт ли порт."""
        return self._is_open

    def write(self, data: bytes) -> int:
        """Записать данные в serial-порт."""
        if not self._is_open:
            raise OSError("Port not open")
        self._write_queue.put(data)
        return len(data)

    def read(self, size: int = 1) -> bytes:
        """Прочитать данные из serial-порта."""
        if not self._is_open:
            raise OSError("Port not open")
        try:
            return self._read_queue.get(timeout=self.timeout)
        except queue.Empty:
            return b""

    def readline(self) -> bytes:
        """Прочитать строку из serial-порта."""
        if not self._is_open:
            raise OSError("Port not open")
        try:
            return self._read_queue.get(timeout=self.timeout)
        except queue.Empty:
            return b""

    def in_waiting(self) -> int:
        """Получить число байтов в ожидании чтения."""
        return self._read_queue.qsize()

    def inject_data(self, data: bytes) -> None:
        """Внедрить данные в очередь чтения (для тестирования)."""
        self._read_queue.put(data)

    def get_written_data(self, timeout: float = 1.0) -> bytes | None:
        """Получить данные, которые были записаны (для тестирования)."""
        try:
            return self._write_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def flush(self) -> None:
        """Очистить буферы."""
        while not self._read_queue.empty():
            self._read_queue.get()
        while not self._write_queue.empty():
            self._write_queue.get()
