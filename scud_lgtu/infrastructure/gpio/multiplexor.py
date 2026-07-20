"""
Поток опроса мультиплексора (Multiplexer) системы СКУД.

Этот модуль реализует поток для периодического опроса мультиплексора, который
мультиплексирует входные сигналы: датчики, кнопки, тревога. Поток перебирает
все адреса мультиплексора, читает входной пин и публикует изменившееся состояние
в очередь событий.

Классы
-------
- Multiplexer: поток опроса мультиплексора

Методы Multiplexer
-------------------
- __init__: инициализировать воркер мультиплексора с контроллером, пинами и очередями
- run: главный цикл опроса мультиплексора
- stop: остановить поток
- _load_pin_masks: загрузить мапинг пинов из конфигурации
"""

import threading
import logging
import time
from queue import Queue, Full
from typing import Tuple, Optional

from scud_lgtu.infrastructure.gpio.controller import GpiodPinController
from scud_lgtu.infrastructure.persistence.event_store import ScudEvent, EventType, EventSource

logger = logging.getLogger(__name__)

# Задержка по умолчанию между выставлением адреса и чтением входа.
# Выбрана с запасом 1.5× относительно реального времени спада ~200 мкс.
_DEFAULT_ADDR_SETTLE_S: float = 0.0005   # 500 мкс (будет переопределено из конфига)
#_DEFAULT_ADDR_SETTLE_S: float = 0.1   # 100 мкс


class Multiplexer:
    """
    Поток опроса мультиплексора.

    Parameters
    ----------
    controller : GpiodPinController
        Инициализированный контроллер GPIO.
    input_pin : str
        Имя пина чтения данных с мультиплексора (например, ``'PL11'``).
    output_pins : tuple of str
        Адресные пины мультиплексора (например, ``('PA6', 'PA11', 'PA12')``).
    output_queue : queue.Queue
        Очередь, в которую кладутся считанные состояния.
    lock : threading.Lock
        Общий лок с ShiftRegWorker для защиты GPIO от гонки.
    stop_event : threading.Event
        Событие остановки — при установке поток завершает работу.
    poll_interval : float, optional
        Пауза между полными проходами по адресам (секунды). По умолчанию 0.02 (будет переопределено из конфига).
    addr_settle_s : float, optional
        Время стабилизации выхода мультиплексора после смены адреса (секунды).
        По умолчанию 500 мкс (с запасом относительно ~200 мкс спада сигнала).
        Задержка выполняется внутри общего лока с ShiftRegWorker,
        чтобы исключить гонку на shared-пинах (PA6 и др.).
    event_queue : queue.Queue, optional
        Общая очередь событий. При изменении состояния мультиплексора
        публикуется ``ScudEvent(type='mux_changed', source='mux')``.
    config : dict, optional
        Конфигурация для автоматического мапинга входов мультиплексора.
        Формат: ``{'mux_inputs': {0: 'input_name_0', 1: 'input_name_1', ...}}``.
        Если не указан - используются адреса (0-7).
    """

    def __init__(
        self,
        controller: GpiodPinController,
        input_pin: str,
        output_pins: Tuple[str, ...],
        output_queue: Queue,
        lock: threading.Lock,
        stop_event: threading.Event,
        poll_interval: float = 0.02,  # Дефолтное значение, будет переопределено из конфига
        addr_settle_s: float = _DEFAULT_ADDR_SETTLE_S,  # Дефолтное значение, будет переопределено из конфига
        event_queue: Optional[Queue] = None,
        config: Optional[dict] = None,
    ):
        """
        Инициализировать воркер мультиплексора.

        Parameters
        ----------
        controller : GpiodPinController
            Инициализированный контроллер GPIO
        input_pin : str
            Имя пина чтения данных с мультиплексора
        output_pins : tuple of str
            Адресные пины мультиплексора
        output_queue : Queue
            Очередь для считанных состояний
        lock : threading.Lock
            Общий лок для защиты GPIO от гонки
        stop_event : threading.Event
            Событие остановки потока
        poll_interval : float, optional
            Пауза между полными проходами по адресам (секунды)
        addr_settle_s : float, optional
            Время стабилизации выхода мультиплексора (секунды)
        event_queue : Queue, optional
            Общая очередь событий
        config : dict, optional
            Конфигурация для мапинга входов
        """
        self._controller = controller
        self._input_pin = input_pin
        self._output_pins = list(output_pins)
        self._output_queue = output_queue
        self._lock = lock
        self._stop_event = stop_event
        self._poll_interval = poll_interval
        self._addr_settle_s = addr_settle_s
        self._event_queue = event_queue
        self._n = len(output_pins)
        # Индексы для быстрого iter: [0, 1, 2, ...]
        self._indices = list(range(self._n))
        # Кэш предыдущего состояния для дельта-фильтрации
        self._prev_state: dict = {}
        self._overflow_logged = False
        
        # Мапинг входов по номерам с именами (опционально)
        self._input_names = {}
        if config:
            self._load_input_names(config)

    def _load_input_names(self, config: dict) -> None:
        """Загрузить мапинг входов из конфигурации."""
        mux_inputs = config.get('mux_inputs', {})
        for num, name in mux_inputs.items():
            self._input_names[num] = name
            logger.debug(f"[Multiplexer] Мапинг: вход {num} -> '{name}'")

    def _work_mux(self) -> None:
        """
        Один полный проход по всем адресам мультиплексора.

        Критически важно: set-адреса и read-вход должны выполняться **под одним
        захватом внешнего лока** — иначе ShiftRegister успеет изменить пины
        PA6/PA11/PA12 (которые одновременно SER_DATA и адресные пины) в
        промежутке между set и read, и мы прочитаем вход для неверного адреса.

        Последовательность для каждого из 2^n адресов:
          1. Захватываем ``self._lock`` (внешний, разделяемый с ShiftRegister).
          2. Устанавливаем адресные пины через ``set_outputs_bulk_nolock``
             (без внутреннего лока контроллера — мы уже под внешним).
          3. Спим ``addr_settle_s`` **внутри** внешнего лока.
             ShiftRegister заблокирован на это время, но задержка мала (300 мкс)
             и не мешает работе регистра между полными проходами мультиплексора.
          4. Читаем входной пин через ``read_pin_nolock``.
          5. Отпускаем лок.
        """
        buf: dict = {}
        for mask in range(2 ** self._n):
            # Формируем словарь {pin: bit} для текущей маски
            values = {
                self._output_pins[i]: (mask >> i) & 1
                for i in self._indices
            }

            # Один захват внешнего лока на весь цикл set → settle → read:
            # ShiftRegister не вмешается в середину последовательности.
            with self._lock:
                # Записываем адрес (nolock — внешний лок уже держим)
                self._controller.set_outputs_bulk_nolock(values)
                # Ждём стабилизации выхода мультиплексора (~200 мкс спада)
                time.sleep(self._addr_settle_s)
                # Читаем входной пин (nolock — внешний лок держим)
                input_state = self._controller.read_pin_nolock(self._input_pin)

            # Используем имя входа из мапинга, если есть
            input_name = self._input_names.get(mask, f"input_{mask}")
            buf[input_name] = input_state

        # Дельта-фильтр: отправляем только при изменении
        if buf != self._prev_state:
            self._prev_state = buf.copy()
            try:
                self._output_queue.put_nowait(buf)
            except Full:
                if not self._overflow_logged:
                    logger.warning("Multiplexer: output_queue переполнена, данные сброшены.")
                    self._overflow_logged = True

            if self._event_queue is not None:
                try:
                    self._event_queue.put_nowait(
                        ScudEvent(
                            type=EventType.MUX_CHANGED,
                            source=EventSource.MUX,
                            payload={"states": buf},
                        )
                    )
                except Full:
                    if not self._overflow_logged:
                        logger.warning("Multiplexer: event_queue переполнена.")
                        self._overflow_logged = True

    def run(self) -> None:
        """
        Основной цикл потока мультиплексора.

        Запускается как target для ``threading.Thread``.
        Завершается при установке ``stop_event``.
        """
        logger.debug(
            "🔄 MuxWorker запущен (input=%s, outputs=%s, settle=%.0f мкс)",
            self._input_pin, self._output_pins, self._addr_settle_s * 1e6,
        )
        while not self._stop_event.is_set():
            try:
                self._work_mux()
            except Exception as e:
                logger.error("MuxWorker ошибка: %s", e, exc_info=True)
            # Короткая пауза между циклами, чтобы не перегружать CPU
            self._stop_event.wait(timeout=self._poll_interval)
        logger.debug("MuxWorker остановлен.")
