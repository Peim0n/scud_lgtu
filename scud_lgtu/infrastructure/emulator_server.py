"""
UDP сервер для приёма команд симуляции от внешних скриптов.

Позволяет управлять эмуляторами из отдельного процесса/консоли.
"""
import socket
import threading
import logging
import json
from typing import Callable, Dict, Any

logger = logging.getLogger(__name__)


class EmulatorUDPServer:
    """
    UDP сервер для приёма команд симуляции.

    Принимает JSON команды на локальный порт и вызывает соответствующие callback-и.
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 9999):
        """
        Инициализировать UDP сервер.

        Parameters
        ----------
        host : str
            Хост для прослушивания
        port : int
            Порт для прослушивания
        """
        self.host = host
        self.port = port
        self._socket = None
        self._thread = None
        self._running = threading.Event()
        self._callbacks: Dict[str, Callable] = {}

    def register_callback(self, command: str, callback: Callable[[Dict[str, Any]], None]):
        """
        Зарегистрировать callback для команды.

        Parameters
        ----------
        command : str
            Имя команды
        callback : callable
            Функция, которая будет вызвана при получении команды
        """
        self._callbacks[command] = callback
        logger.info(f"[EmulatorUDPServer] Registered callback for command: {command}")

    def start(self):
        """Запустить UDP сервер."""
        if self._thread is not None and self._thread.is_alive():
            logger.warning("[EmulatorUDPServer] Server already running")
            return

        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._socket.bind((self.host, self.port))
        self._socket.settimeout(0.1)  # Таймаут для возможности остановки

        self._running.set()
        self._thread = threading.Thread(target=self._listen_loop, daemon=True)
        self._thread.start()

        logger.info(f"[EmulatorUDPServer] Server started on {self.host}:{self.port}")

    def stop(self):
        """Остановить UDP сервер."""
        if self._thread is None or not self._thread.is_alive():
            logger.info("[EmulatorUDPServer] Server not running")
            return

        self._running.clear()
        self._thread.join(timeout=2.0)

        if self._socket:
            self._socket.close()
            self._socket = None

        logger.info("[EmulatorUDPServer] Server stopped")

    def _listen_loop(self):
        """Основной цикл прослушивания."""
        logger.info("[EmulatorUDPServer] Listening for commands...")

        while self._running.is_set():
            try:
                data, addr = self._socket.recvfrom(4096)
                try:
                    command = json.loads(data.decode('utf-8'))
                    cmd_type = command.get('cmd')

                    if cmd_type in self._callbacks:
                        logger.info(f"[EmulatorUDPServer] Received command: {cmd_type} from {addr}")
                        self._callbacks[cmd_type](command)
                    else:
                        logger.warning(f"[EmulatorUDPServer] Unknown command: {cmd_type}")
                except json.JSONDecodeError as e:
                    logger.error(f"[EmulatorUDPServer] Invalid JSON: {e}")
                except Exception as e:
                    logger.error(f"[EmulatorUDPServer] Error processing command: {e}")

            except socket.timeout:
                continue
            except Exception as e:
                if self._running.is_set():
                    logger.error(f"[EmulatorUDPServer] Error in listen loop: {e}")
                break

        logger.info("[EmulatorUDPServer] Listen loop ended")
