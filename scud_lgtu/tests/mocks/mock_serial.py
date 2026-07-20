"""Mock serial port for testing without hardware."""
import queue
from typing import Optional


class MockSerialPort:
    """Mock serial port that simulates pyserial behavior."""
    
    def __init__(self, port: str = "/dev/ttyUSB0", baudrate: int = 9600, timeout: float = 1.0):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self._is_open = False
        self._read_queue = queue.Queue()
        self._write_queue = queue.Queue()
    
    def open(self) -> None:
        """Open the serial port."""
        self._is_open = True
    
    def close(self) -> None:
        """Close the serial port."""
        self._is_open = False
    
    def is_open(self) -> bool:
        """Check if port is open."""
        return self._is_open
    
    def write(self, data: bytes) -> int:
        """Write data to serial port."""
        if not self._is_open:
            raise IOError("Port not open")
        self._write_queue.put(data)
        return len(data)
    
    def read(self, size: int = 1) -> bytes:
        """Read data from serial port."""
        if not self._is_open:
            raise IOError("Port not open")
        try:
            return self._read_queue.get(timeout=self.timeout)
        except queue.Empty:
            return b""
    
    def readline(self) -> bytes:
        """Read a line from serial port."""
        if not self._is_open:
            raise IOError("Port not open")
        try:
            return self._read_queue.get(timeout=self.timeout)
        except queue.Empty:
            return b""
    
    def in_waiting(self) -> int:
        """Get number of bytes waiting to be read."""
        return self._read_queue.qsize()
    
    def inject_data(self, data: bytes) -> None:
        """Inject data into read queue (for testing)."""
        self._read_queue.put(data)
    
    def get_written_data(self, timeout: float = 1.0) -> Optional[bytes]:
        """Get data that was written (for testing)."""
        try:
            return self._write_queue.get(timeout=timeout)
        except queue.Empty:
            return None
    
    def flush(self) -> None:
        """Flush buffers."""
        while not self._read_queue.empty():
            self._read_queue.get()
        while not self._write_queue.empty():
            self._write_queue.get()
