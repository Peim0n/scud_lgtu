"""
Контроллер GPIO-пинов на базе gpiod (libgpiod v2).

Заменяет оригинальный OPZPinController (mmap / /dev/mem) на современный
интерфейс gpiod, который:
  * не требует root-доступа к /dev/mem;
  * переносим между платами;
  * безопасно работает в многопоточной среде через threading.Lock.

Поддерживаемые операции
-----------------------
* set_pin_modes()     — настроить направление пинов (input/output)
* set_pull_up()       — включить pull-up (через LineSettings bias)
* set_output_states() — выставить уровни на выходных пинах
* set_outputs_bulk()  — атомарная запись нескольких пинов за раз
* set_drive_strength()— заглушка для совместимости API (gpiod не управляет drive strength)
* write_pin()         — запись одного пина
* read_pin()          — чтение одного пина
* get_snapshot()      — прочитать все зарегистрированные пины
* close()             — освободить все линии gpiod

Соответствие имён пинов (из config.yml) → chip + offset
---------------------------------------------------------
Имена вида PA6, PL11 и т.д. трактуются через таблицу PIN_MAP.
Если имя не найдено — используется числовой offset на gpiochip0.
"""

import threading
import logging
from typing import Dict, List, Optional, Tuple

import gpiod
from gpiod.line import Direction, Value, Bias

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Таблица: имя пина (из config.yml) → (chip_path, line_offset)
# Платформа: Orange Pi Zero (Allwinner H2+/H3)
#   gpiochip0 — банки PA, PG
#   gpiochip1 — банк PL (R_PIO)
# ---------------------------------------------------------------------------
PIN_MAP: Dict[str, Tuple[str, int]] = {
    # ── PORT A (gpiochip0, base offset = A * 32) ──
    "PA0":  ("/dev/gpiochip0",  0),
    "PA1":  ("/dev/gpiochip0",  1),
    "PA3":  ("/dev/gpiochip0",  3),
    "PA6":  ("/dev/gpiochip0",  6),
    "PA7":  ("/dev/gpiochip0",  7),
    "PA8":  ("/dev/gpiochip0",  8),
    "PA9":  ("/dev/gpiochip0",  9),
    "PA10": ("/dev/gpiochip0", 10),
    "PA11": ("/dev/gpiochip0", 11),
    "PA12": ("/dev/gpiochip0", 12),
    "PA13": ("/dev/gpiochip0", 13),
    "PA14": ("/dev/gpiochip0", 14),
    "PA18": ("/dev/gpiochip0", 18),
    "PA19": ("/dev/gpiochip0", 19),
    "PA20": ("/dev/gpiochip0", 20),
    "PA21": ("/dev/gpiochip0", 21),
    # ── PORT G (gpiochip0, base offset = 6 * 32 = 192) ──
    "PG6":  ("/dev/gpiochip0", 198),
    "PG7":  ("/dev/gpiochip0", 199),
    # ── PORT L (gpiochip1, R_PIO) ──
    "PL11": ("/dev/gpiochip1", 11),
}

# gpiod Value для уровней 0/1
_LEVEL_TO_VALUE = {0: Value.INACTIVE, 1: Value.ACTIVE}
_VALUE_TO_LEVEL = {Value.INACTIVE: 0, Value.ACTIVE: 1}


class GpiodPinController:
    """
    Контроллер GPIO на базе gpiod (libgpiod ≥ 2.x).

    Все пины одного chip объединяются в один ``request_lines``-запрос
    для минимизации количества открытых файловых дескрипторов и ускорения
    атомарных операций ``set_values`` / ``get_values``.

    Parameters
    ----------
    pin_map : dict, optional
        Таблица ``{pin_name: (chip_path, offset)}``.
        По умолчанию используется модульная константа ``PIN_MAP``.

    Notes
    -----
    Контроллер необходимо инициализировать вызовом :meth:`open` перед
    использованием. Рекомендуется использовать как контекстный менеджер::

        with GpiodPinController() as ctrl:
            ctrl.open({...})
            ...
    """

    def __init__(self, pin_map: Optional[Dict[str, Tuple[str, int]]] = None):
        """Инициализировать контроллер GPIO. Открытие линий — в open()."""
        self._pin_map: Dict[str, Tuple[str, int]] = pin_map or PIN_MAP
        # chip_path → {offset: LineSettings}
        self._chip_configs: Dict[str, Dict[int, gpiod.LineSettings]] = {}
        # chip_path → LineRequest
        self._requests: Dict[str, gpiod.LineRequest] = {}
        # pin_name → (chip_path, offset, direction)
        self._pin_info: Dict[str, Tuple[str, int, str]] = {}
        # Защита от одновременных операций записи/чтения из разных потоков
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Инициализация / настройка
    # ------------------------------------------------------------------

    def open(self, modes: Dict[str, str], pull_ups: Optional[List[str]] = None) -> None:
        """
        Захватить линии gpiod и настроить направления.

        Parameters
        ----------
        modes : dict
            ``{pin_name: 'input' | 'output'}``
        pull_ups : list of str, optional
            Список пинов (режим input), на которых нужен pull-up.
        """
        pull_up_set = set(pull_ups or [])

        # Группируем пины по chip
        chip_settings: Dict[str, Dict[int, gpiod.LineSettings]] = {}
        for pin_name, mode_str in modes.items():
            if pin_name not in self._pin_map:
                logger.warning("Пин %s не найден в PIN_MAP, пропущен.", pin_name)
                continue
            chip_path, offset = self._pin_map[pin_name]
            direction = Direction.OUTPUT if mode_str.lower() == "output" else Direction.INPUT
            bias = Bias.PULL_UP if pin_name in pull_up_set else Bias.AS_IS

            settings = gpiod.LineSettings(
                direction=direction,
                output_value=Value.INACTIVE,
                bias=bias,
            )
            chip_settings.setdefault(chip_path, {})[offset] = settings
            self._pin_info[pin_name] = (chip_path, offset, mode_str.lower())

        # Открываем request для каждого chip
        for chip_path, cfg in chip_settings.items():
            if chip_path in self._requests:
                # Уже открыт — освобождаем и переоткрываем с новой конфигурацией
                self._requests[chip_path].release()
            req = gpiod.request_lines(chip_path, consumer="scud-controller", config=cfg)
            self._requests[chip_path] = req
            logger.info("[GpiodPinController] %s: захвачены линии %s", chip_path, list(cfg.keys()))

    def set_pin_modes(self, modes: Dict[str, str]) -> None:
        """
        Настроить направления пинов (совместимость с OPZPinController API).

        Если request для данного chip ещё не создан — создаёт новый.
        Если уже открыт — пересоздаёт с обновлённой конфигурацией.

        Parameters
        ----------
        modes : dict
            ``{pin_name: 'input' | 'output'}``
        """
        self.open(modes)

    def set_pull_up(self, pins: List[str]) -> None:
        """
        Включить pull-up на входных пинах.

        Пересоздаёт LineSettings для указанных пинов с Bias.PULL_UP.

        Parameters
        ----------
        pins : list of str
            Имена пинов, на которых нужен pull-up.
        """
        with self._lock:
            for pin_name in pins:
                if pin_name not in self._pin_info:
                    logger.warning("set_pull_up: пин %s не инициализирован.", pin_name)
                    continue
                chip_path, offset, direction = self._pin_info[pin_name]
                req = self._requests.get(chip_path)
                if req is None:
                    continue
                # Перенастраиваем bias через reconfigure_lines
                try:
                    req.reconfigure_lines(
                        {offset: gpiod.LineSettings(
                            direction=Direction.INPUT,
                            bias=Bias.PULL_UP,
                        )}
                    )
                    logger.info("↑ Pull-UP включён на %s (offset=%d)", pin_name, offset)
                except Exception as e:
                    logger.warning("Не удалось установить pull-up на %s: %s", pin_name, e)

    def set_drive_strength(self, pins: List[str], strength: int = 2) -> None:
        """
        Заглушка для совместимости с OPZPinController API.

        gpiod не управляет drive strength — этот параметр задаётся
        аппаратно или через Device Tree.

        Parameters
        ----------
        pins : list of str
            Список пинов (игнорируется).
        strength : int
            Значение силы тока (игнорируется).
        """
        logger.debug(
            "set_drive_strength: gpiod не управляет drive strength. "
            "Настройте через Device Tree. Пины: %s, strength=%d",
            pins, strength,
        )

    # ------------------------------------------------------------------
    # Запись
    # ------------------------------------------------------------------

    def write_pin(self, pin_name: str, level: int) -> None:
        """
        Записать уровень (0 или 1) на один пин.

        Parameters
        ----------
        pin_name : str
            Имя пина, например ``'PA6'``.
        level : int
            ``0`` (LOW) или ``1`` (HIGH).

        Raises
        ------
        ValueError
            Если пин не инициализирован.
        """
        if pin_name not in self._pin_info:
            raise ValueError(f"Пин {pin_name} не инициализирован. Вызовите open() / set_pin_modes().")
        chip_path, offset, _ = self._pin_info[pin_name]
        req = self._requests[chip_path]
        val = Value.ACTIVE if level else Value.INACTIVE
        with self._lock:
            req.set_value(offset, val)

    # Псевдоним для совместимости с OPZPinController
    _write_pin = write_pin

    def set_output_states(self, states: Dict[str, int]) -> None:
        """
        Установить уровни на нескольких пинах (поочерёдно).

        Parameters
        ----------
        states : dict
            ``{pin_name: 0 | 1}``
        """
        with self._lock:
            for pin_name, level in states.items():
                if pin_name not in self._pin_info:
                    logger.warning("set_output_states: пин %s не инициализирован.", pin_name)
                    continue
                chip_path, offset, _ = self._pin_info[pin_name]
                req = self._requests[chip_path]
                req.set_value(offset, Value.ACTIVE if level else Value.INACTIVE)

    def set_outputs_bulk(self, states: Dict[str, int]) -> None:
        """
        Атомарная запись нескольких пинов за один вызов (по chip).

        Группирует пины по chip и вызывает ``set_values`` для каждого chip,
        что минимизирует количество ioctl-вызовов.

        Parameters
        ----------
        states : dict
            ``{pin_name: 0 | 1}``
        """
        if not states:
            return

        # Группируем по chip для пакетной записи
        chip_values: Dict[str, Dict[int, Value]] = {}
        for pin_name, level in states.items():
            if pin_name not in self._pin_info:
                logger.warning("set_outputs_bulk: пин %s не инициализирован.", pin_name)
                continue
            chip_path, offset, _ = self._pin_info[pin_name]
            chip_values.setdefault(chip_path, {})[offset] = Value.ACTIVE if level else Value.INACTIVE

        with self._lock:
            for chip_path, values in chip_values.items():
                req = self._requests.get(chip_path)
                if req:
                    req.set_values(values)

    def write_pin_nolock(self, pin_name: str, level: int) -> None:
        """
        Записать уровень пина **без захвата внутреннего лока**.

        Вызывайте только когда уже держите внешний лок
        (например, изнутри ``ShiftRegWorker._work_shift``).

        Parameters
        ----------
        pin_name : str
            Имя пина, например ``'PA19'``.
        level : int
            ``0`` (LOW) или ``1`` (HIGH).
        """
        if pin_name not in self._pin_info:
            raise ValueError(f"Пин {pin_name} не инициализирован.")
        chip_path, offset, _ = self._pin_info[pin_name]
        req = self._requests[chip_path]
        req.set_value(offset, Value.ACTIVE if level else Value.INACTIVE)

    def set_outputs_bulk_nolock(self, states: Dict[str, int]) -> None:
        """
        Запись нескольких пинов **без захвата внутреннего лока**.

        Вызывайте только когда уже держите внешний лок (например, в MuxWorker),
        чтобы избежать двойного локирования и позволить удержать внешний лок
        на всё время ``set → sleep → read``.

        Parameters
        ----------
        states : dict
            ``{pin_name: 0 | 1}``
        """
        if not states:
            return
        chip_values: Dict[str, Dict[int, Value]] = {}
        for pin_name, level in states.items():
            if pin_name not in self._pin_info:
                continue
            chip_path, offset, _ = self._pin_info[pin_name]
            chip_values.setdefault(chip_path, {})[offset] = Value.ACTIVE if level else Value.INACTIVE
        for chip_path, values in chip_values.items():
            req = self._requests.get(chip_path)
            if req:
                req.set_values(values)

    def read_pin_nolock(self, pin_name: str) -> int:
        """
        Чтение одного пина **без захвата внутреннего лока**.

        Вызывайте только когда уже держите внешний лок.

        Parameters
        ----------
        pin_name : str
            Имя пина.

        Returns
        -------
        int
            ``0`` (LOW) или ``1`` (HIGH).
        """
        if pin_name not in self._pin_info:
            raise ValueError(f"Пин {pin_name} не инициализирован.")
        chip_path, offset, _ = self._pin_info[pin_name]
        req = self._requests[chip_path]
        val = req.get_value(offset)
        return 1 if val == Value.ACTIVE else 0

    # ------------------------------------------------------------------
    # Чтение
    # ------------------------------------------------------------------

    def read_pin(self, pin_name: str) -> int:
        """
        Прочитать уровень пина.

        Parameters
        ----------
        pin_name : str
            Имя пина.

        Returns
        -------
        int
            ``0`` (LOW) или ``1`` (HIGH).
        """
        if pin_name not in self._pin_info:
            raise ValueError(f"Пин {pin_name} не инициализирован.")
        chip_path, offset, _ = self._pin_info[pin_name]
        req = self._requests[chip_path]
        with self._lock:
            val = req.get_value(offset)
        return 1 if val == Value.ACTIVE else 0

    def get_snapshot(self) -> Dict[str, int]:
        """
        Прочитать текущие уровни всех инициализированных пинов.

        Returns
        -------
        dict
            ``{pin_name: 0 | 1}`` — состояние каждого пина.
        """
        snapshot: Dict[str, int] = {}
        # Для каждого chip читаем все линии одним вызовом
        chip_offsets: Dict[str, List[int]] = {}
        offset_to_pin: Dict[str, Dict[int, str]] = {}
        for pin_name, (chip_path, offset, _) in self._pin_info.items():
            chip_offsets.setdefault(chip_path, []).append(offset)
            offset_to_pin.setdefault(chip_path, {})[offset] = pin_name

        with self._lock:
            for chip_path, offsets in chip_offsets.items():
                req = self._requests.get(chip_path)
                if req is None:
                    continue
                values = req.get_values(offsets)
                for offset, val in zip(offsets, values):
                    pin_name = offset_to_pin[chip_path][offset]
                    snapshot[pin_name] = 1 if val == Value.ACTIVE else 0
        return snapshot

    # Алиас для совместимости: старый API возвращал bytearray + get_snapshot_state
    def get_snapshot_state(self, snapshot: Dict[str, int]) -> Dict[str, int]:
        """
        Совместимость с OPZPinController.

        В новом API snapshot уже является словарём ``{pin_name: level}``,
        поэтому этот метод просто возвращает аргумент без изменений.

        Parameters
        ----------
        snapshot : dict
            Результат :meth:`get_snapshot`.

        Returns
        -------
        dict
            Тот же словарь.
        """
        return snapshot

    # ------------------------------------------------------------------
    # Управление ресурсами
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Освободить все захваченные линии gpiod."""
        with self._lock:
            for chip_path, req in list(self._requests.items()):
                try:
                    req.release()
                    logger.info("[GpiodPinController] %s: линии освобождены.", chip_path)
                except Exception as e:
                    logger.warning("Ошибка при освобождении %s: %s", chip_path, e)
            self._requests.clear()
            self._pin_info.clear()

    def __enter__(self) -> "GpiodPinController":
        """Вход в контекстный менеджер."""
        return self

    def __exit__(self, *args) -> None:
        """Выход из контекстного менеджера — освобождаем GPIO."""
        self.close()

    def __del__(self) -> None:
        """Деструктор — пытаемся освободить GPIO."""
        self.close()
