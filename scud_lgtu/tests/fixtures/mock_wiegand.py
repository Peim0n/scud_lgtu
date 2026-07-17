"""
Mock Wiegand Reader для тестирования без аппаратного обеспечения.

Эмулирует поведение WiegandReader для запуска тестов на любой машине.
"""
import threading
import logging
import time
from queue import Queue
from dataclasses import dataclass
from typing import Optional, List

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


class MockWiegandReader:
    """
    Mock WiegandReader для тестирования.

    Эмулирует поведение WiegandReader без реального GPIO.
    Позволяет симулировать считывание карт.
    """

    def __init__(
        self,
        d0_pin: str = "PA0",
        d1_pin: str = "PA1",
        reader_id: str = "Wiegand-1",
        bit_timeout: float = 0.025,
        wait_timeout: float = 0.005,
    ):
        """
        Инициализировать mock Wiegand reader.

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
        """
        self.d0_pin = d0_pin
        self.d1_pin = d1_pin
        self.reader_id = reader_id
        self.bit_timeout = bit_timeout
        self.wait_timeout = wait_timeout

        self.queue: Queue = Queue()
        self._running = threading.Event()
        self._thread: Optional[threading.Thread] = None

        # Для симуляции входящих карт
        self._card_queue: Queue = Queue()

        # Для отслеживания вызовов
        self.card_reads: List[CardData] = []

    def _read_loop(self) -> None:
        """Рабочий цикл потока (mock)."""
        logger.info(f"[MockWiegandReader] Запуск потока для {self.reader_id}")

        try:
            while self._running.is_set():
                try:
                    # Симулируем считывание карты из очереди
                    if not self._card_queue.empty():
                        card_data = self._card_queue.get(timeout=0.01)
                        logger.info(f"[MockWiegandReader] Card read: {card_data.card_uid} from {self.reader_id}")
                        self.queue.put(card_data)
                        self.card_reads.append(card_data)
                    else:
                        time.sleep(0.01)  # Нет данных - ждём

                except Exception as e:
                    logger.warning(f"[MockWiegandReader] Ошибка: {e}")
                    time.sleep(0.01)
        finally:
            logger.info(f"[MockWiegandReader] Поток {self.reader_id} завершён")

    def start(self) -> Queue:
        """
        Запустить фоновый поток считывания.

        Returns
        -------
        queue.Queue
            Очередь считанных карт
        """
        if self._thread is not None and self._thread.is_alive():
            logger.warning(f"[MockWiegandReader] Поток {self.reader_id} уже запущен")
            return self.queue

        self._running.set()
        self._thread = threading.Thread(
            target=self._read_loop,
            name=f"MockWiegandReader-{self.reader_id}",
            daemon=True,
        )
        self._thread.start()
        logger.info(f"[MockWiegandReader] Поток запущен для {self.reader_id}")
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
            logger.info(f"[MockWiegandReader] Поток {self.reader_id} не запущен")
            return

        self._running.clear()
        self._thread.join(timeout=timeout)

        if self._thread.is_alive():
            logger.warning(f"[MockWiegandReader] Поток {self.reader_id} не завершился за {timeout}s")
        else:
            logger.info(f"[MockWiegandReader] Поток {self.reader_id} остановлен")

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
        logger.debug(f"[MockWiegandReader] Simulated card read: {card_uid}")

    def simulate_card_reads(self, card_uids: List[str]):
        """
        Симулировать считывание нескольких карт.

        Parameters
        ----------
        card_uids : list
            Список UID карт
        """
        for card_uid in card_uids:
            self.simulate_card_read(card_uid)
        logger.debug(f"[MockWiegandReader] Simulated {len(card_uids)} card reads")

    def reset(self):
        """Сбросить состояние reader."""
        self._card_queue.queue.clear()
        self.queue.queue.clear()
        self.card_reads.clear()
        logger.info(f"[MockWiegandReader] Reader {self.reader_id} reset")

    def get_state(self) -> dict:
        """
        Получить состояние reader (для тестов).

        Returns
        -------
        dict
            Состояние reader
        """
        return {
            "reader_id": self.reader_id,
            "d0_pin": self.d0_pin,
            "d1_pin": self.d1_pin,
            "is_alive": self.is_alive(),
            "card_queue_size": self._card_queue.qsize(),
            "output_queue_size": self.queue.qsize(),
            "card_reads_count": len(self.card_reads),
        }


class MockWiegandReaderManager:
    """
    Менеджер нескольких mock Wiegand readers.

    Позволяет управлять несколькими считывателями одновременно.
    """

    def __init__(self):
        """Инициализировать менеджер."""
        self._readers: dict[str, MockWiegandReader] = {}

    def add_reader(
        self,
        reader_id: str,
        d0_pin: str = "PA0",
        d1_pin: str = "PA1",
        bit_timeout: float = 0.025,
        wait_timeout: float = 0.005,
    ) -> MockWiegandReader:
        """
        Добавить считыватель.

        Parameters
        ----------
        reader_id : str
            Идентификатор считывателя
        d0_pin : str
            Имя пина D0
        d1_pin : str
            Имя пина D1
        bit_timeout : float
            Таймаут между битами
        wait_timeout : float
            Таймаут ожидания событий

        Returns
        -------
        MockWiegandReader
            Созданный reader
        """
        reader = MockWiegandReader(
            d0_pin=d0_pin,
            d1_pin=d1_pin,
            reader_id=reader_id,
            bit_timeout=bit_timeout,
            wait_timeout=wait_timeout,
        )
        self._readers[reader_id] = reader
        logger.info(f"[MockWiegandReaderManager] Added reader: {reader_id}")
        return reader

    def get_reader(self, reader_id: str) -> Optional[MockWiegandReader]:
        """
        Получить считыватель по ID.

        Parameters
        ----------
        reader_id : str
            Идентификатор считывателя

        Returns
        -------
        MockWiegandReader or None
            Reader или None если не найден
        """
        return self._readers.get(reader_id)

    def start_all(self) -> dict[str, Queue]:
        """
        Запустить все считыватели.

        Returns
        -------
        dict
            {reader_id: queue}
        """
        queues = {}
        for reader_id, reader in self._readers.items():
            queues[reader_id] = reader.start()
        logger.info(f"[MockWiegandReaderManager] Started {len(self._readers)} readers")
        return queues

    def stop_all(self, timeout: float = 5.0):
        """
        Остановить все считыватели.

        Parameters
        ----------
        timeout : float
            Максимальное время ожидания
        """
        for reader in self._readers.values():
            reader.stop(timeout)
        logger.info(f"[MockWiegandReaderManager] Stopped {len(self._readers)} readers")

    def reset_all(self):
        """Сбросить все считыватели."""
        for reader in self._readers.values():
            reader.reset()
        logger.info(f"[MockWiegandReaderManager] Reset {len(self._readers)} readers")

    def simulate_card_read(self, reader_id: str, card_uid: str):
        """
        Симулировать считывание карты на конкретном считывателе.

        Parameters
        ----------
        reader_id : str
            Идентификатор считывателя
        card_uid : str
            UID карты
        """
        reader = self.get_reader(reader_id)
        if reader:
            reader.simulate_card_read(card_uid)
        else:
            logger.warning(f"[MockWiegandReaderManager] Reader {reader_id} not found")

    def get_all_states(self) -> dict[str, dict]:
        """
        Получить состояние всех считывателей.

        Returns
        -------
        dict
            {reader_id: state}
        """
        return {reader_id: reader.get_state() for reader_id, reader in self._readers.items()}
