"""
Поток записи данных в сдвиговый регистр (ShiftRegister) системы СКУД.

Этот модуль реализует поток для записи данных в последовательный сдвиговый регистр.
Поток ожидает числовые сообщения в очереди и при получении выдаёт биты MSB-first
через линии SER_DATA / SER_CLK / SER_LATCH.

Классы
-------
- ShiftRegister: поток записи данных в последовательный сдвиговый регистр

Методы ShiftRegister
---------------------
- __init__: инициализировать воркер сдвигового регистра с контроллером, пинами и очередями
- run: главный цикл записи данных в регистр
- stop: остановить поток
- _load_pin_masks: загрузить мапинг пинов из конфигурации
- set_mask: установить состояние нескольких пинов по именам
"""

import threading
import logging
from queue import Queue, Empty, Full
from typing import Any, Optional

from scud_lgtu.infrastructure.gpio.controller import GpiodPinController
from scud_lgtu.infrastructure.persistence.event_store import ScudEvent, EventType, EventSource
from scud_lgtu.infrastructure.config.module_resolver import ModuleResolver

logger = logging.getLogger(__name__)


class ShiftRegister:
    """
    Поток записи данных в последовательный сдвиговый регистр.

    Parameters
    ----------
    controller : GpiodPinController
        Инициализированный контроллер GPIO.
    input_queue : queue.Queue
        Очередь входящих значений (int).
    lock : threading.Lock
        Общий лок с Multiplexer.
    stop_event : threading.Event
        Событие остановки.
    event_queue : queue.Queue, optional
        Общая очередь событий. После успешной записи публикуется
        ``ScudEvent(type='shift_done', source='shift')``.
    resolver : ModuleResolver
        Резолвер модульных имен для конфигурации.
    config : dict, optional
        Полный конфигурационный словарь (для обратной совместимости).
    """

    def __init__(
        self,
        controller: GpiodPinController,
        input_queue: Queue,
        lock: threading.Lock,
        stop_event: threading.Event,
        event_queue: Optional[Queue] = None,
        resolver: Optional[ModuleResolver] = None,
        config: Optional[dict] = None,
    ):
        """Инициализировать воркер сдвигового регистра."""
        self._controller = controller
        self._input_queue = input_queue
        self._lock = lock
        self._stop_event = stop_event
        self._event_queue = event_queue
        self._resolver = resolver

        # Автоматический мапинг пинов
        self._pin_masks = {}
        self._last_sent_state = 0  # Последнее состояние, отправленное в регистр

        # Загрузка конфигурации
        if resolver:
            # Новая архитектура с ModuleResolver
            self._load_from_resolver()
        elif config:
            # Старая архитектура для обратной совместимости
            self._load_pin_masks(config)
        else:
            raise ValueError("Either resolver or config must be provided")

        # Получение пинов сдвигового регистра
        if resolver:
            resolver.set_context("shift_register")
            self._ser_data_pin = resolver.resolve("ser_data")
            self._ser_clk_pin = resolver.resolve("ser_clk")
            self._ser_latch_pin = resolver.resolve("ser_latch")
            self._n = resolver.resolve("reg_len")
        elif config:
            # Старая архитектура
            self._ser_data_pin = config.get("ser_data", "PA6")
            self._ser_clk_pin = config.get("ser_clk", "PA19")
            self._ser_latch_pin = config.get("ser_latch", "PA7")
            self._n = config.get("reg_len", 16)

    def _load_from_resolver(self) -> None:
        """Загрузить мапинг пинов из ModuleResolver."""
        if not self._resolver:
            return

        self._resolver.set_context("shift_register")
        pins_config = self._resolver.resolve("pins")

        for name, cfg in pins_config.items():
            offset = cfg.get('offset')
            inverted = cfg.get('inverted', False)
            if offset is not None:
                mask = 1 << offset
                if inverted:
                    mask = ~mask & ((1 << self._n) - 1)  # Инвертировать в пределах reg_len
                self._pin_masks[name] = mask
                logger.info(f"[ShiftRegister] Мапинг: {name} -> offset={offset}, inverted={inverted}, mask=0x{mask:04x}")

    def _load_pin_masks(self, config: dict) -> None:
        """Загрузить мапинг пинов из конфигурации (старая архитектура)."""
        shift_pins = config.get('shift_pins', {})
        for name, cfg in shift_pins.items():
            pin = cfg.get('pin')
            inverted = cfg.get('inverted', False)
            if pin is not None:
                mask = 1 << pin
                if inverted:
                    mask = ~mask & ((1 << self._n) - 1)  # Инвертировать в пределах reg_len
                self._pin_masks[name] = mask
                logger.info(f"[ShiftRegister] Мапинг (legacy): {name} -> pin={pin}, inverted={inverted}, mask=0x{mask:04x}")

    def set_mask(self, masks: dict[str, bool]) -> None:
        """
        Установить несколько масок атомарно по именам.

        Parameters
        ----------
        masks : dict[str, bool]
            Словарь {'mask_name': state, ...} где state=True/False.
        """
        with self._lock:
            new_state = self._last_sent_state
            logger.info(f"[ShiftRegister] set_mask: last_sent_state={self._last_sent_state:#06x}, masks={masks}")
            for name, state in masks.items():
                # Резолвим бизнес-имена в прямые имена пинов
                resolved_name = self._resolve_name(name)
                
                if resolved_name not in self._pin_masks:
                    logger.warning(f"[ShiftRegister] Неизвестная маска: {resolved_name} (original: {name})")
                    continue
                mask = self._pin_masks[resolved_name]
                logger.info(f"[ShiftRegister] Processing {resolved_name}: state={state}, mask={mask:#06x}")
                if state:
                    new_state |= mask
                else:
                    new_state &= ~mask
                logger.info(f"[ShiftRegister] After {resolved_name}: new_state={new_state:#06x}")
            logger.info(f"[ShiftRegister] Putting new_state={new_state:#06x} into queue")
            self._input_queue.put(new_state, timeout=1.0)
            # Сразу обновляем last_sent_state, чтобы следующие команды видели новое состояние
            self._last_sent_state = new_state
    
    def _resolve_name(self, name: str) -> str:
        """Разрешить бизнес-имя в прямое имя пина."""
        # Если имя содержит точку - это уже прямой мапинг
        if '.' in name:
            return name
        
        # Пытаемся разрешить через business секцию
        if self._resolver is not None:
            try:
                self._resolver.set_context("business")
                resolved = self._resolver.resolve(name)
                
                # Если результат - строка с точкой, возвращаем её (это прямой мапинг)
                if isinstance(resolved, str) and '.' in resolved:
                    return resolved
            except Exception as e:
                logger.debug(f"[ShiftRegister] Could not resolve name {name}: {e}")
        
        # Возвращаем как есть
        return name

    def _work_shift(self, value: Any) -> None:
        """
        Записать значение в сдвиговый регистр (MSB-first).

        Вызывается уже под захваченным ``self._lock`` (внешним),
        поэтому использует ``write_pin_nolock`` — без лишнего внутреннего
        захвата. Это убирает ~48 лишних Lock.__enter__ на одну передачу
        16-битного слова.

        Для каждого бита (от старшего к младшему):
          1. Установить SER_DATA = бит.
          2. Импульс CLK: 0 → 1 → 0.
        После всех битов — импульс LATCH: 0 → 1 → 0.

        Parameters
        ----------
        value : int
            Число для записи. Используются ``reg_len`` младших бит.
        """
        logger.info(f"[ShiftRegister] _work_shift: writing value={value:#06x} to shift register")
        wp = self._controller.write_pin_nolock
        for i in range(self._n - 1, -1, -1):
            bit = (value >> i) & 1
            wp(self._ser_data_pin, bit)
            wp(self._ser_clk_pin, 0)
            wp(self._ser_clk_pin, 1)
            wp(self._ser_clk_pin, 0)
        # Защёлка: передаём накопленные данные на выходы регистра
        wp(self._ser_latch_pin, 0)
        wp(self._ser_latch_pin, 1)
        wp(self._ser_latch_pin, 0)
        logger.info(f"[ShiftRegister] _work_shift: written value={value:#06x}")
        
        # Обновляем последнее отправленное состояние
        self._last_sent_state = value

    def run(self) -> None:
        """
        Основной цикл потока сдвигового регистра.

        Блокируется на очереди, при получении сообщения записывает
        значение в регистр под локом. Завершается при установке
        ``stop_event`` (очередь будет разблокирована по timeout).
        """
        logger.info(
            "⚡ ShiftRegWorker запущен (DATA=%s CLK=%s LATCH=%s bits=%d)",
            self._ser_data_pin, self._ser_clk_pin, self._ser_latch_pin, self._n,
        )
        while not self._stop_event.is_set():
            try:
                # Ждём сообщение с таймаутом, чтобы проверять stop_event
                msg = self._input_queue.get(timeout=0.1)
                if msg is None:
                    # None используется как sentinel для остановки
                    continue
                with self._lock:
                    self._work_shift(msg)
                if self._event_queue is not None:
                    try:
                        self._event_queue.put_nowait(
                            ScudEvent(
                                type=EventType.SHIFT_DONE,
                                source=EventSource.SHIFT,
                                payload={"value": msg, "bits": self._n},
                            )
                        )
                    except Full:
                        pass
            except Empty:
                # Таймаут — проверяем stop_event и ждём дальше
                continue
            except Exception as e:
                logger.error("ShiftRegWorker ошибка: %s", e, exc_info=True)
        logger.info("ShiftRegWorker остановлен.")
