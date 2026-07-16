"""
Поток считывания карт по протоколу Wiegand (WeigandReader).

Полная замена оригинального ``wiegand_reader.WeigandReader`` с переходом
с ``multiprocessing.Process`` на ``threading.Thread``.

Протокол Wiegand
----------------
Считыватель передаёт биты по двум линиям (D0 и D1):
  * Импульс LOW на D0 — передаётся бит «0».
  * Импульс LOW на D1 — передаётся бит «1».
Пауза между битами не превышает BIT_TIMEOUT.

Архитектура
-----------
Поток блокируется через ``select`` на файловом дескрипторе gpiod.
При появлении события считывает его, накапливает биты, и когда
набирается нужное число (total_bits) или истекает BIT_TIMEOUT —
обрабатывает карту и кладёт ``CardData`` в выходную очередь.

Форматы Wiegand
---------------
Поддерживаемые форматы определены в словаре ``WEIGAND_FORMATS``:
26, 33, 34, 37, 40, 42, 66 бит, а также ERA MF 64 hash.
"""

import threading
import logging
import re
import time
from dataclasses import dataclass
from queue import Queue, Full
from typing import Optional
import datetime

import gpiod
from gpiod.line import Edge, Bias

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Разрешение имён пинов
# ---------------------------------------------------------------------------

# Формат: PA<N>, PG<N>, PL<N> — как в config.yml и pin_controller.PIN_MAP.
# PA и PG находятся на gpiochip0, PL — на gpiochip1.
_PIN_RE = re.compile(r"^(PA|PG|PL)(\d+)$", re.IGNORECASE)
_PIN_BANK_BASE = {
    "PA": ("/dev/gpiochip0", 0),
    "PG": ("/dev/gpiochip0", 192),
    "PL": ("/dev/gpiochip1", 0),
}


def _resolve_pin(pin: str | int) -> tuple[str, int]:
    """
    Преобразовать имя пина или offset в (chip_path, line_offset).

    Parameters
    ----------
    pin : str | int
        Имя пина (PA<N>, PG<N>, PL<N>) или числовой offset.

    Returns
    -------
    tuple[str, int]
        (chip_path, line_offset)
    """
    if isinstance(pin, int):
        return "/dev/gpiochip0", pin

    m = _PIN_RE.match(pin)
    if not m:
        # Пробуем интерпретировать как offset
        try:
            return "/dev/gpiochip0", int(pin)
        except ValueError as exc:
            raise ValueError(f"Некорректное имя пина Wiegand: {pin}") from exc

    bank, num = m.group(1).upper(), int(m.group(2))
    chip_path, base = _PIN_BANK_BASE[bank]
    return chip_path, base + num


# ---------------------------------------------------------------------------
# Константы
# ---------------------------------------------------------------------------

DEFAULT_BIT_TIMEOUT: float = 0.025
"""Максимальный интервал между двумя последовательными битами (с)."""

DEFAULT_WAIT_TIMEOUT: float = 0.005
"""Таймаут ожидания события gpiod в основном цикле (с)."""

MAX_BITS_SAFETY: int = 90
"""Максимальное число накопленных бит до принудительного сброса."""


# ---------------------------------------------------------------------------
# Форматы Wiegand
# ---------------------------------------------------------------------------

@dataclass
class WiegandFormat:
    """Описание одного формата Wiegand."""
    total_bits: int
    """Общее число бит в кадре (включая биты чётности)."""
    data_bits: int
    """Число информационных бит данных."""
    parity_scheme: str
    """Схема чётности: ``'none'``, ``'even_odd'``, ``'single_even'``, ``'single_odd'``."""


WEIGAND_FORMATS = {
    26:  WiegandFormat(26,  24, "even_odd"),   # 1-й: чётность первых 12, 26-й: нечётность последних 12
    33:  WiegandFormat(33,  32, "single_even"),# 1-й: чётность всех 32 бит
    34:  WiegandFormat(34,  32, "even_odd"),   # 1-й: чётность первых 16, 34-й: нечётность последних 16
    37:  WiegandFormat(37,  35, "even_odd"),   # 1-й/37-й: чётность половин
    40:  WiegandFormat(40,  40, "none"),
    42:  WiegandFormat(42,  40, "even_odd"),   # 1-й: чётность первых 20, 42-й: нечётность последних 20
    66:  WiegandFormat(66,  64, "even_odd"),   # 1-й: чётность первых 32, 66-й: нечётность последних 32
    "era_mf_64_hash": WiegandFormat(64, 64, "none"),  # 64 бита (hash)
}


# ---------------------------------------------------------------------------
# Результат чтения
# ---------------------------------------------------------------------------

@dataclass
class CardData:
    """Результат считывания карты."""
    card_data: Optional[int]
    """Декодированный номер карты (без бит чётности). None при ошибке."""
    raw_data: Optional[int]
    """Сырые данные (без бит чётности). None при ошибке."""
    bit_sequence: str
    """Полная битовая последовательность в виде строки."""
    is_valid: bool
    """True, если биты чётности прошли проверку."""
    error_message: Optional[str] = None
    """Описание ошибки при is_valid == False."""


# ---------------------------------------------------------------------------
# Основной класс
# ---------------------------------------------------------------------------

class WeigandReader:
    """
    Поток считывания карт Wiegand по двум линиям D0/D1.

    Parameters
    ----------
    chip_path : str
        Путь к GPIO-chip, например ``'/dev/gpiochip0'``.
        Используется только если ``d0``/``d1`` переданы как числовые offset.
        Если пины переданы именами (PA<N>, PG<N>, PL<N>), chip определяется автоматически.
    d0 : str | int
        Имя пина (PA<N>, PG<N>, PL<N>) или offset для D0.
    d1 : str | int
        Имя пина (PA<N>, PG<N>, PL<N>) или offset для D1.
    wiegand_type : int or str
        Тип формата Wiegand (ключ из ``WEIGAND_FORMATS``).
    encrypted : bool
        True, если данные с считывателя зашифрованы.
        При True накопленные биты расшифровываются через ``decrypt_key``
        перед парсингом формата.
    decrypt_key : str | bytes | None
        Ключ для расшифровки Wiegand-данных. Используется только при
        ``encrypted=True``. Формат и алгоритм зависят от модели считывателя.
    output_queue : queue.Queue
        Очередь для передачи считанных карт в главный поток.
    running_event : threading.Event, optional
        Событие работы. Если None — создаётся автоматически и устанавливается.
    """

    def __init__(
        self,
        d0: str | int = 11,
        d1: str | int = 12,
        chip_path: str = "/dev/gpiochip0",
        wiegand_type: int = 26,
        encrypted: bool = False,
        decrypt_key: str | bytes | None = None,
        output_queue: Optional[Queue] = None,
        running_event: Optional[threading.Event] = None,
        bit_timeout: float = DEFAULT_BIT_TIMEOUT,
        wait_timeout: float = DEFAULT_WAIT_TIMEOUT,
    ):
        """Инициализировать Wiegand-читатель с пинами и форматом."""
        d0_chip, d0_offset = _resolve_pin(d0)
        d1_chip, d1_offset = _resolve_pin(d1)

        if d0_chip != d1_chip:
            raise ValueError(
                f"Пины D0 ({d0_chip}) и D1 ({d1_chip}) должны быть на одном GPIO-chip"
            )

        self.chip_path = d0_chip
        self.d0_offset = d0_offset
        self.d1_offset = d1_offset
        self.encrypted = encrypted
        self.decrypt_key = decrypt_key
        self.output_queue = output_queue
        self.bit_timeout = bit_timeout
        self.wait_timeout = wait_timeout

        if wiegand_type not in WEIGAND_FORMATS:
            raise ValueError(
                f"Неподдерживаемый тип Wiegand: {wiegand_type}. "
                f"Доступные: {list(WEIGAND_FORMATS.keys())}"
            )
        fmt = WEIGAND_FORMATS[wiegand_type]
        self.total_bits: int = fmt.total_bits
        self.data_bits_count: int = fmt.data_bits
        self.parity_scheme: str = fmt.parity_scheme

        # Событие: is_set() == поток работает
        self.running = running_event or threading.Event()
        self.running.set()

        # Буфер накопленных бит текущего кадра
        self._bits: list = []
        self._last_bit_time: float = 0.0
        self._reading: bool = False
        self._cards_read: int = 0

        # gpiod request (открывается в open())
        self._request: Optional[gpiod.LineRequest] = None

    # ------------------------------------------------------------------
    # Инициализация GPIO
    # ------------------------------------------------------------------

    def open(self) -> None:
        """
        Захватить линии D0 и D1 через gpiod.

        Raises
        ------
        Exception
            При ошибке открытия gpiod линий.
        """
        logger.info(
            "[WeigandReader] Инициализация GPIO на %s для Wiegand-%d (D0=%d D1=%d)",
            self.chip_path, self.total_bits, self.d0_offset, self.d1_offset,
        )
        self._request = gpiod.request_lines(
            self.chip_path,
            consumer=f"wiegand-{self.total_bits}",
            config={
                self.d0_offset: gpiod.LineSettings(
                    direction=gpiod.line.Direction.INPUT,
                    edge_detection=Edge.FALLING,
                    bias=Bias.PULL_UP,
                ),
                self.d1_offset: gpiod.LineSettings(
                    direction=gpiod.line.Direction.INPUT,
                    edge_detection=Edge.FALLING,
                    bias=Bias.PULL_UP,
                ),
            },
        )
        logger.info(
            "[WeigandReader] ✓ Линии настроены: D0=%d D1=%d",
            self.d0_offset, self.d1_offset,
        )

    # ------------------------------------------------------------------
    # Обработка бит и карт
    # ------------------------------------------------------------------

    def _process_bit(self, bit_value: int) -> None:
        """
        Добавить бит в буфер и проверить таймаут / завершение кадра.

        Parameters
        ----------
        bit_value : int
            0 (D0 сработал) или 1 (D1 сработал).
        """
        current_time = time.time()

        if self._reading:
            elapsed = current_time - self._last_bit_time
            if elapsed > self.bit_timeout:
                logger.debug(
                    "[WeigandReader] Сброс: перерыв %.1f мс > %.0f мс",
                    elapsed * 1000, self.bit_timeout * 1000,
                )
                self._reset_reading()

        if not self._reading:
            # Начало нового кадра
            self._reading = True
            self._bits = [bit_value]
            self._last_bit_time = current_time
        else:
            self._bits.append(bit_value)
            self._last_bit_time = current_time

            if len(self._bits) == self.total_bits:
                # Кадр полностью накоплен — декодируем
                self._process_card()
            elif len(self._bits) > MAX_BITS_SAFETY:
                logger.warning("[WeigandReader] Превышен MAX_BITS_SAFETY (%d). Сброс.", MAX_BITS_SAFETY)
                self._send_invalid_card("Превышено максимальное количество бит")
                self._reset_reading()

    def _decrypt_bits(self, bit_seq: str) -> str:
        """
        Расшифровать Wiegand-битовую последовательность.

        Заглушка: реальная реализация зависит от модели считывателя.
        Если ``encrypted=True`` и ключ/алгоритм не настроены,
        возвращает исходную последовательность и логирует предупреждение.
        """
        if not self.encrypted:
            return bit_seq

        if not self.decrypt_key:
            logger.warning(
                "[WeigandReader] Получены зашифрованные данные, но decrypt_key не задан"
            )
            return bit_seq

        # TODO: реализовать расшифровку под конкретный алгоритм считывателя
        logger.warning("[WeigandReader] Расшифровка Wiegand не реализована, возвращаем как есть")
        return bit_seq

    def _process_card(self) -> None:
        """
        Декодировать накопленный кадр и положить CardData в очередь.
        """
        if len(self._bits) != self.total_bits:
            self._send_invalid_card(
                f"Неполная последовательность ({len(self._bits)}/{self.total_bits} бит)"
            )
            self._reset_reading()
            return

        self._cards_read += 1
        bit_seq = "".join(str(b) for b in self._bits)

        # Если данные зашифрованы — расшифровываем перед парсингом
        bit_seq = self._decrypt_bits(bit_seq)
        self._bits = [int(b) for b in bit_seq]

        if len(self._bits) != self.total_bits:
            self._send_invalid_card("Расшифровка изменила длину кадра")
            self._reset_reading()
            return

        card_data: Optional[int] = None
        raw_data: Optional[int] = None
        is_valid = True
        error_msg: Optional[str] = None
        data_bits_list: list

        if self.parity_scheme == "none":
            data_bits_list = self._bits[:]

        elif self.parity_scheme == "even_odd":
            first_parity = self._bits[0]
            last_parity = self._bits[self.total_bits - 1]
            data_bits_list = self._bits[1:self.total_bits - 1]
            half = self.data_bits_count // 2
            first_half = data_bits_list[:half]
            second_half = data_bits_list[half:]
            if not (
                self._check_even_parity(first_parity, first_half)
                and self._check_odd_parity(last_parity, second_half)
            ):
                is_valid = False
                error_msg = "Ошибка чётности (even/odd)"

        elif self.parity_scheme == "single_even":
            single_parity = self._bits[0]
            data_bits_list = self._bits[1:]
            if not self._check_even_parity(single_parity, data_bits_list):
                is_valid = False
                error_msg = "Ошибка чётности (single even)"

        elif self.parity_scheme == "single_odd":
            single_parity = self._bits[0]
            data_bits_list = self._bits[1:]
            if not self._check_odd_parity(single_parity, data_bits_list):
                is_valid = False
                error_msg = "Ошибка чётности (single odd)"
        else:
            data_bits_list = self._bits[:]

        if is_valid and self.data_bits_count > 0:
            raw_data = int("".join(str(b) for b in data_bits_list), 2)
            card_data = raw_data & 0xFFFF_FFFF_FFFF_FFFF

        result = CardData(
            card_data=card_data,
            raw_data=raw_data,
            bit_sequence=bit_seq,
            is_valid=is_valid,
            error_message=error_msg,
        )

        logger.info(
            "[WeigandReader] КАРТА #%d (Wiegand-%d) — %s%s",
            self._cards_read,
            self.total_bits,
            "✓" if is_valid else f"✗ ({error_msg})",
            f" № {card_data}" if is_valid else "",
        )

        if self.output_queue is not None:
            try:
                self.output_queue.put_nowait(result)
            except Exception as e:
                logger.error("[WeigandReader] Ошибка добавления в очередь: %s", e)

        self._reset_reading()

    def _send_invalid_card(self, error_msg: str) -> None:
        """Сформировать и отправить невалидный CardData."""
        result = CardData(
            card_data=None,
            raw_data=None,
            bit_sequence="".join(str(b) for b in self._bits),
            is_valid=False,
            error_message=error_msg,
        )
        logger.warning("[WeigandReader] Карта невалидна: %s", error_msg)
        if self.output_queue is not None:
            try:
                self.output_queue.put_nowait(result)
            except Exception as e:
                logger.error("[WeigandReader] Ошибка добавления в очередь: %s", e)

    def _reset_reading(self) -> None:
        """Сбросить буфер накопления бит."""
        self._bits = []
        self._reading = False
        self._last_bit_time = 0.0

    # ------------------------------------------------------------------
    # Проверки чётности
    # ------------------------------------------------------------------

    @staticmethod
    def _check_even_parity(parity_bit: int, data: list) -> bool:
        """
        Проверить чётный бит паритета.

        Для even parity: parity_bit = 0 если число единиц чётное.
        """
        ones = sum(data)
        return parity_bit == (0 if ones % 2 == 0 else 1)

    @staticmethod
    def _check_odd_parity(parity_bit: int, data: list) -> bool:
        """
        Проверить нечётный бит паритета.

        Для odd parity: parity_bit = 0 если число единиц нечётное.
        """
        ones = sum(data)
        return parity_bit == (0 if ones % 2 == 1 else 1)

    # ------------------------------------------------------------------
    # Основной цикл
    # ------------------------------------------------------------------

    def run(self) -> None:
        """
        Основной цикл потока.

        Используется как ``target`` для ``threading.Thread``.
        Блокируется на ``wait_edge_events`` — поток не грузит CPU в ожидании.
        Завершается при сбросе ``running``.
        """
        try:
            self.open()
            while self.running.is_set():
                # Блокируемся ядром на wait_timeout, потом проверяем таймаут кадра
                if self._request.wait_edge_events(datetime.timedelta(seconds=self.wait_timeout)):
                    for event in self._request.read_edge_events():
                        bit = 0 if event.line_offset == self.d0_offset else 1
                        self._process_bit(bit)

                # Принудительная обработка по таймауту (если не набралось total_bits)
                if self._reading and (time.time() - self._last_bit_time > self.bit_timeout):
                    logger.debug(
                        "[WeigandReader] Таймаут: %d бит накоплено, обрабатываем.",
                        len(self._bits),
                    )
                    self._process_card()
                    self._reset_reading()

        except Exception as e:
            if self.running.is_set():
                logger.error("[WeigandReader] Критическая ошибка: %s", e, exc_info=True)
        finally:
            if self._request:
                self._request.release()
                self._request = None
                logger.info("[WeigandReader] ✓ GPIO линии освобождены.")
            logger.info("[WeigandReader] Поток завершён.")

    # ------------------------------------------------------------------
    # Фабричный метод
    # ------------------------------------------------------------------

    @classmethod
    def start(
        cls,
        d0: str | int,
        d1: str | int,
        wiegand_type: int = 26,
        chip_path: str = "/dev/gpiochip0",
        encrypted: bool = False,
        decrypt_key: str | bytes | None = None,
        bit_timeout: float = DEFAULT_BIT_TIMEOUT,
        wait_timeout: float = DEFAULT_WAIT_TIMEOUT,
    ):
        """
        Создать экземпляр, запустить в фоновом потоке и вернуть управляющие объекты.

        Parameters
        ----------
        d0 : str | int
            Имя пина (PA<N>, PG<N>, PL<N>) или GPIO offset для D0.
        d1 : str | int
            Имя пина (PA<N>, PG<N>, PL<N>) или GPIO offset для D1.
        wiegand_type : int or str
            Формат Wiegand.
        chip_path : str
            Путь к GPIO chip (используется только при числовых offset).
        encrypted : bool
            True, если считыватель передаёт зашифрованные данные.
        decrypt_key : str | bytes | None
            Ключ для расшифровки.
        bit_timeout : float
            Максимальный интервал между битами.
        wait_timeout : float
            Таймаут ожидания gpiod-события.

        Returns
        -------
        tuple
            ``(thread, queue, event)`` — поток, очередь CardData, событие остановки.
        """
        q: Queue = Queue()
        ev = threading.Event()
        ev.set()
        reader = cls(
            d0=d0,
            d1=d1,
            chip_path=chip_path,
            wiegand_type=wiegand_type,
            encrypted=encrypted,
            decrypt_key=decrypt_key,
            output_queue=q,
            running_event=ev,
            bit_timeout=bit_timeout,
            wait_timeout=wait_timeout,
        )
        t = threading.Thread(
            target=reader.run,
            name=f"WeigandReader-{wiegand_type}",
            daemon=True,
        )
        t.start()
        return t, q, ev
