"""
Эмулятор Wiegand Reader для работы без аппаратного обеспечения.

Эмулирует поведение WeigandReader без реального GPIO.
Полностью совместим по API с WeigandReader.
"""
import threading
import logging
import time
import sys
from queue import Queue
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class CardData:
    """Данные считанной карты."""
    card_uid: str
    """UID карты в строковом представлении."""
    reader_id: str
    """Идентификатор считывателя."""
    timestamp: float
    """Время считывания (Unix timestamp)."""


class EmulatorWiegandReader:
    """
    Эмулятор Wiegand Reader.

    Эмулирует поведение WeigandReader без реального GPIO.
    Позволяет симулировать считывание карт через консоль или программно.
    """

    def __init__(
        self,
        d0_pin: str = "PA0",
        d1_pin: str = "PA1",
        reader_id: str = "Wiegand-1",
        bit_timeout: float = 0.025,
        wait_timeout: float = 0.005,
        console_input: bool = True,
    ):
        """
        Инициализировать эмулятор Wiegand reader.

        Parameters
        ----------
        d0_pin : str
            Имя пина D0
        d1_pin : str
            Имя пина D1
        reader_id : str
            Идентификатор считывателя
        bit_timeout : float
            Таймаут между битами
        wait_timeout : float
            Таймаут ожидания событий
        console_input : bool
            Если True, читает карты из консоли (stdin). По умолчанию False.
        """
        self.d0_pin = d0_pin
        self.d1_pin = d1_pin
        self.reader_id = reader_id
        self.bit_timeout = bit_timeout
        self.wait_timeout = wait_timeout
        self.console_input = console_input

        self.queue: Queue = Queue()
        self._running = threading.Event()
        self._thread: Optional[threading.Thread] = None

        # Для симуляции входящих карт
        self._card_queue: Queue = Queue()

        logger.info(f"[EmulatorWiegandReader] Initialized for {reader_id} (emulation mode)")

    def _read_loop(self) -> None:
        """Рабочий цикл потока (эмуляция)."""
        logger.info(f"[EmulatorWiegandReader] Запуск потока для {self.reader_id}")

        if self.console_input:
            logger.info(f"[EmulatorWiegandReader] Чтение карт из консоли для {self.reader_id}")
            print(f"[EmulatorWiegandReader] Введите UID карты для {self.reader_id} и нажмите Enter:")
            print(f"[EmulatorWiegandReader] Для остановки нажмите Ctrl+C или введите 'quit'")

        try:
            while self._running.is_set():
                try:
                    # Сначала проверяем программную очередь
                    if not self._card_queue.empty():
                        card_data = self._card_queue.get(timeout=0.01)
                        logger.info(f"[EmulatorWiegandReader] Card read: {card_data.card_uid} from {self.reader_id}")
                        self.queue.put(card_data)
                    elif self.console_input:
                        # Читаем из консоли
                        try:
                            line = sys.stdin.readline().strip()
                            if line and line.lower() != 'quit':
                                card_data = CardData(
                                    card_uid=line,
                                    reader_id=self.reader_id,
                                    timestamp=time.time()
                                )
                                logger.info(f"[EmulatorWiegandReader] Card read: {line} from {self.reader_id}")
                                self.queue.put(card_data)
                            elif line.lower() == 'quit':
                                logger.info(f"[EmulatorWiegandReader] Получен 'quit', остановка {self.reader_id}")
                                self._running.clear()
                        except EOFError:
                            time.sleep(0.1)
                        except Exception as e:
                            logger.warning(f"[EmulatorWiegandReader] Ошибка чтения из консоли: {e}")
                            time.sleep(0.1)
                    else:
                        time.sleep(0.01)  # Нет данных - ждём

                except Exception as e:
                    logger.warning(f"[EmulatorWiegandReader] Ошибка: {e}")
                    time.sleep(0.01)
        finally:
            logger.info(f"[EmulatorWiegandReader] Поток {self.reader_id} завершён")

    def start(self) -> Queue:
        """
        Запустить фоновый поток считывания.

        Returns
        -------
        queue.Queue
            Очередь считанных карт
        """
        if self._thread is not None and self._thread.is_alive():
            logger.warning(f"[EmulatorWiegandReader] Поток {self.reader_id} уже запущен")
            return self.queue

        self._running.set()
        self._thread = threading.Thread(
            target=self._read_loop,
            name=f"EmulatorWiegandReader-{self.reader_id}",
            daemon=True,
        )
        self._thread.start()
        logger.info(f"[EmulatorWiegandReader] Поток запущен для {self.reader_id}")
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
            logger.info(f"[EmulatorWiegandReader] Поток {self.reader_id} не запущен")
            return

        self._running.clear()
        self._thread.join(timeout=timeout)

        if self._thread.is_alive():
            logger.warning(f"[EmulatorWiegandReader] Поток {self.reader_id} не завершился за {timeout}s")
        else:
            logger.info(f"[EmulatorWiegandReader] Поток {self.reader_id} остановлен")

    def is_alive(self) -> bool:
        """Жив ли фоновый поток."""
        return self._thread is not None and self._thread.is_alive()

    def simulate_card_read(self, card_uid: str):
        """
        Симулировать считывание карты.

        Parameters
        ----------
        card_uid : str
            UID карты
        """
        card_data = CardData(
            card_uid=card_uid,
            reader_id=self.reader_id,
            timestamp=time.time()
        )
        self._card_queue.put(card_data)
        logger.debug(f"[EmulatorWiegandReader] Simulated card read: {card_uid}")

    def open(self):
        """Открыть reader (эмуляция)."""
        logger.info(f"[EmulatorWiegandReader] Opened (emulation mode)")

    def close(self):
        """Закрыть reader (эмуляция)."""
        logger.info(f"[EmulatorWiegandReader] Closed (emulation mode)")

    def reset(self):
        """Сбросить состояние reader."""
        self._card_queue.queue.clear()
        self.queue.queue.clear()
        logger.info(f"[EmulatorWiegandReader] Reader {self.reader_id} reset")
