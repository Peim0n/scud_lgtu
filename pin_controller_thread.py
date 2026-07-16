"""
Менеджер фоновых потоков для управления GPIO-контроллером (PinControllerThread).

Аналог оригинального ``PinControllerProcess``, но реализован на
``threading.Thread`` вместо ``multiprocessing.Process``.

Преимущества потоков перед процессами в данном контексте
--------------------------------------------------------
* Нет необходимости в ``fork``-безопасной передаче контроллера —
  все потоки делят одну копию ``GpiodPinController``.
* Меньше накладных расходов: очереди — ``queue.Queue`` (без pickle),
  события — ``threading.Event``.
* Не требуется bridge-корутина для перекладывания данных между
  ``asyncio.Queue`` и ``multiprocessing.Queue``.

Принципиальное отличие от оригинала (PinControllerProcess)
-----------------------------------------------------------
``PinControllerThread`` **не создаёт собственный** ``GpiodPinController``.
Вместо этого он принимает уже открытый контроллер извне — это позволяет
главному потоку и воркерам разделять **один** gpiod-request на одни
и те же линии, не получая ``EBUSY`` при повторном захвате.

Публичный интерфейс
-------------------
* ``shift_input_queue`` — кладите сюда int-значения для сдвигового регистра.
* ``mux_output_queue`` — читайте отсюда состояния мультиплексора (dict).
* :meth:`start` — запустить фоновые потоки.
* :meth:`stop`  — корректно остановить все потоки (контроллер НЕ закрывает).
"""

import threading
import logging
from typing import Optional
from queue import Queue

from .pin_controller import GpiodPinController
from .mux_worker import MuxWorker
from .shift_reg_worker import ShiftRegWorker

logger = logging.getLogger(__name__)


class PinControllerThread:
    """
    Запускает MuxWorker и ShiftRegWorker в фоновых потоках.

    Принимает уже инициализированный ``GpiodPinController`` — это
    позволяет главному потоку (например, для прямого теста GPIO) и
    воркерам совместно использовать **один** gpiod-request, не вызывая
    конфликта ``EBUSY``.

    После вызова :meth:`start`:
      * MuxWorker непрерывно опрашивает мультиплексор и кладёт
        результаты в :attr:`mux_output_queue`.
      * ShiftRegWorker ожидает значения в :attr:`shift_input_queue`
        и записывает их в сдвиговый регистр.

    Оба потока разделяют один ``threading.Lock`` для защиты GPIO.
    Этот же лок может быть передан извне для синхронизации с
    дополнительным кодом в главном потоке.

    Parameters
    ----------
    controller : GpiodPinController
        Уже открытый (``open()`` вызван) контроллер GPIO. Воркеры
        используют его напрямую; :meth:`stop` контроллер **не закрывает** —
        за это отвечает вызывающая сторона.
    mux_input : str
        Имя входного пина мультиплексора (например, ``'PL11'``).
    mux_outputs : tuple of str
        Адресные пины мультиплексора (например, ``('PA6', 'PA11', 'PA12')``).
    shift_ser_data : str
        Пин SER_DATA сдвигового регистра.
    shift_ser_clk : str
        Пин SER_CLK сдвигового регистра.
    shift_ser_latch : str
        Пин SER_LATCH сдвигового регистра.
    shift_reg_len : int
        Разрядность сдвигового регистра (бит), например 16.
    lock : threading.Lock, optional
        Внешний лок для защиты GPIO. Если не передан — создаётся новый.
        Передайте тот же лок в главный поток, если он тоже обращается к GPIO.
    mux_poll_interval : float, optional
        Пауза между полными проходами мультиплексора (с). По умолчанию 0.02.
    mux_addr_settle_s : float, optional
        Время стабилизации мультиплексора после смены адреса (с).
        По умолчанию 500 мкс.
    event_queue : queue.Queue, optional
        Общая очередь событий. MuxWorker публикует ``mux_changed``,
        ShiftRegWorker — ``shift_done``.

    Attributes
    ----------
    shift_input_queue : queue.Queue
        Очередь для передачи значений сдвиговому регистру.
    mux_output_queue : queue.Queue
        Очередь с результатами опроса мультиплексора.
    lock : threading.Lock
        Лок, разделяемый между воркерами (и опционально главным потоком).
    """

    def __init__(
        self,
        controller: GpiodPinController,
        mux_input: str,
        mux_outputs: tuple,
        shift_ser_data: str,
        shift_ser_clk: str,
        shift_ser_latch: str,
        shift_reg_len: int,
        lock: Optional[threading.Lock] = None,
        mux_poll_interval: float = 0.02,
        mux_addr_settle_s: float = 500e-6,
        event_queue: Optional[Queue] = None,
    ):
        """Подготовить потоки GPIO для мультиплексора и сдвигового регистра."""
        # Принимаем готовый контроллер — не создаём новый,
        # чтобы не конфликтовать с уже открытыми линиями gpiod.
        self._controller = controller
        self._mux_input = mux_input
        self._mux_outputs = tuple(mux_outputs)
        self._shift_ser_data = shift_ser_data
        self._shift_ser_clk = shift_ser_clk
        self._shift_ser_latch = shift_ser_latch
        self._shift_reg_len = shift_reg_len
        self._mux_poll_interval = mux_poll_interval
        self._mux_addr_settle_s = mux_addr_settle_s
        self._event_queue = event_queue

        # Публичные очереди (доступны из главного потока сразу после __init__)
        self.shift_input_queue: Queue = Queue(maxsize=50)
        self.mux_output_queue: Queue = Queue(maxsize=100)

        # Единый лок — используется воркерами и может быть передан снаружи
        # (главный поток тоже должен брать этот лок при прямой работе с GPIO)
        self.lock: threading.Lock = lock if lock is not None else threading.Lock()

        self._stop_event: threading.Event = threading.Event()
        self._mux_thread: threading.Thread | None = None
        self._shift_thread: threading.Thread | None = None

    def start(self) -> None:
        """
        Запустить фоновые потоки MuxWorker и ShiftRegWorker.

        Контроллер должен быть уже инициализирован до вызова этого метода.
        Если потоки уже запущены — вызов игнорируется.
        """
        if self._mux_thread is not None and self._mux_thread.is_alive():
            logger.warning("PinControllerThread: уже запущен, повторный start() игнорируется.")
            return

        self._stop_event.clear()
        logger.info("📌 PinControllerThread: запуск воркеров на переданном контроллере…")

        # Создаём воркеры, передавая им общий контроллер и лок
        mux = MuxWorker(
            controller=self._controller,
            input_pin=self._mux_input,
            output_pins=self._mux_outputs,
            output_queue=self.mux_output_queue,
            lock=self.lock,
            stop_event=self._stop_event,
            poll_interval=self._mux_poll_interval,
            addr_settle_s=self._mux_addr_settle_s,
            event_queue=self._event_queue,
        )
        shift = ShiftRegWorker(
            controller=self._controller,
            input_queue=self.shift_input_queue,
            ser_data_pin=self._shift_ser_data,
            ser_clk_pin=self._shift_ser_clk,
            ser_latch_pin=self._shift_ser_latch,
            reg_len=self._shift_reg_len,
            lock=self.lock,
            stop_event=self._stop_event,
            event_queue=self._event_queue,
        )

        # Запускаем потоки (daemon=True — завершаются вместе с главным процессом)
        self._mux_thread = threading.Thread(
            target=mux.run, name="MuxWorker", daemon=True
        )
        self._shift_thread = threading.Thread(
            target=shift.run, name="ShiftRegWorker", daemon=True
        )
        self._mux_thread.start()
        self._shift_thread.start()
        logger.info("📌 PinControllerThread: потоки MuxWorker и ShiftRegWorker запущены")

    def stop(self, timeout: float = 2.0) -> None:
        """
        Остановить фоновые потоки.

        .. note::
            Контроллер GPIO **не закрывается** — это ответственность
            вызывающей стороны (той, кто создавал ``GpiodPinController``).

        Parameters
        ----------
        timeout : float
            Максимальное время ожидания завершения каждого потока (с).
        """
        logger.info("PinControllerThread: остановка…")
        self._stop_event.set()

        # Будим ShiftRegWorker, если он заблокирован на пустой очереди
        try:
            self.shift_input_queue.put_nowait(None)
        except Exception:
            pass

        for t in (self._mux_thread, self._shift_thread):
            if t is not None and t.is_alive():
                t.join(timeout=timeout)
                if t.is_alive():
                    logger.warning("Поток %s не завершился вовремя.", t.name)

        logger.info("PinControllerThread: остановлен.")

    def is_running(self) -> bool:
        """Вернуть True, если оба рабочих потока живы."""
        return (
            self._mux_thread is not None and self._mux_thread.is_alive()
            and self._shift_thread is not None and self._shift_thread.is_alive()
        )
