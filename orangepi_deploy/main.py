#!/usr/bin/env python3
"""
Интерактивное меню для тестирования всех модулей СКУД (gpiod + threading версия).

Меню
----
  1. Сдвиговый регистр — отправка значения через очередь в фоновый поток
  2. Мультиплексор — опрос через фоновый поток (вывод в реальном времени)
  3. Wiegand считыватели (1 и 2)
  4. Серийные порты (1 и 2)
  5. Прямой тест GPIO (набор пинов из config)
  0. Выход

Конфигурация — ../config.yml (относительно этого файла).

Отличия от оригинального main.py
---------------------------------
* Вместо ``multiprocessing.Process`` — ``threading.Thread`` (нет fork).
* Вместо OPZPinController (mmap) — GpiodPinController (gpiod).
* Нет диагностики mmap — вместо неё упрощённый прямой тест GPIO.
* Очереди — ``queue.Queue`` (без pickle-накладных расходов).
"""

import sys
import select
import time
import logging
import threading

# Добавляем родительскую директорию в путь, чтобы найти config.yml
import os

# Настройка логирования: INFO для наших модулей, WARNING для остального
logging.basicConfig(
    level=logging.WARNING,
    format="%(name)s [%(levelname)s] %(message)s",
)
logging.getLogger("scud_lgtu").setLevel(logging.INFO)

from scud_lgtu.pin_controller import GpiodPinController
from scud_lgtu.pin_controller_thread import PinControllerThread
from scud_lgtu.wiegand_reader import WeigandReader, CardData
from scud_lgtu.serial_reader import BackgroundSerialReader
import scud_lgtu.config as config

# ---------------------------------------------------------------------------
# Загрузка конфигурации
# ---------------------------------------------------------------------------
cfg = config.load()

# Конфигурация сдвигового регистра
SR = cfg["shift"]
# Конфигурация мультиплексора
MUX = cfg["mux"]
# Список конфигураций Wiegand-считывателей
WG = cfg["wiegand"]
# Список конфигураций серийных портов
SER = cfg["serial"]


# ---------------------------------------------------------------------------
# Меню
# ---------------------------------------------------------------------------

def print_menu() -> None:
    """Вывести главное меню."""
    print("\n" + "=" * 60)
    print("         ТЕСТОВОЕ МЕНЮ СКУД  [gpiod + threading]")
    print("=" * 60)
    print(" 1. Ввод 2 байт на сдвиговый регистр")
    print(" 2. Мониторинг мультиплексора (реальное время)")
    print(" 3. Чтение с Wiegand (1 и 2)")
    print(" 4. Чтение с серийного порта (1 и 2)")
    print(" 5. Прямой тест GPIO (set/read пины из config)")
    print(" 0. Выход")
    print("=" * 60)


# ---------------------------------------------------------------------------
# Пункт 1 — Сдвиговый регистр
# ---------------------------------------------------------------------------

def shift_reg_test(pct: PinControllerThread) -> None:
    """
    Отправить 2 байта (16 бит) на сдвиговый регистр.

    Пользователь вводит HEX-значение; оно кладётся в shift_input_queue,
    откуда ShiftRegWorker асинхронно запишет биты MSB-first.

    Parameters
    ----------
    pct : PinControllerThread
        Запущенный менеджер фоновых потоков.
    """
    try:
        val = input("  Введите 2 байта в HEX (0000-FFFF, Enter = пропуск): ").strip()
        if not val:
            return
        value = int(val, 16)
        if not (0 <= value <= 0xFFFF):
            print("  ❌ Число должно быть в диапазоне 0000–FFFF")
            return
    except ValueError:
        print("  ❌ Некорректный HEX")
        return

    pct.shift_input_queue.put(value)
    print(f"  ✅ Отправлено 0x{value:04X} ({value:016b}) в очередь сдвигового регистра")


# ---------------------------------------------------------------------------
# Пункт 2 — Мультиплексор
# ---------------------------------------------------------------------------

def mux_test(pct: PinControllerThread) -> None:
    """
    Вывести состояния мультиплексора в реальном времени.

    Читает данные из mux_output_queue и выводит их на экран.
    Для возврата в меню нажмите Enter.

    Parameters
    ----------
    pct : PinControllerThread
        Запущенный менеджер фоновых потоков.
    """
    addr_labels = MUX.get("addr_labels", MUX["addr_pins"])
    input_pin   = MUX["input_pin"]

    print(f"\n{'─' * 60}")
    print("  Мониторинг мультиплексора (реальное время)")
    print(f"  Вход чтения:      {input_pin}")
    print(f"  Адресные выводы:  {', '.join(reversed(addr_labels))}")
    print("  Нажмите Enter для возврата в меню.")
    

    try:
        while True:
            # Вычитываем все накопленные пакеты из очереди
            while not pct.mux_output_queue.empty():
                try:
                    data: dict = pct.mux_output_queue.get_nowait()
                    print(f"{'─' * 60}")
                    addr_text = 'Адрес \n\r ' + ' '.join(reversed(addr_labels))
                    print(f"  {addr_text:<20} Значение")
                    print(f"{'─' * 60}")
                    for key, val in data.items():    
                        bits = [s.split()[-1] for s in key.strip("{}").split(",")]
                        bits_str = "  ".join(reversed(bits))
                        print(f"  {bits_str:<20} {val}")
                except Exception:
                    break

            # Ждём нажатия Enter или следующего пакета
            rlist, _, _ = select.select([sys.stdin], [], [], 0.3)
            if rlist:
                sys.stdin.readline()
                break

    except KeyboardInterrupt:
        pass

    print(f"{'─' * 60}\n")


# ---------------------------------------------------------------------------
# Пункт 3 — Wiegand
# ---------------------------------------------------------------------------

def wiegand_test() -> None:
    """
    Запустить Wiegand-считыватели в фоновых потоках и выводить карты.

    Создаёт по одному потоку WeigandReader на каждый считыватель из config.
    Завершается по Ctrl+C.
    """
    readers = []
    try:
        for w in WG:
            print(f"  🔵 {w['label']}: D0={w['d0']} D1={w['d1']} тип={w['type']}")
        print("     Нажмите Ctrl+C для возврата в меню.\n")

        for w in WG:
            t, q, ev = WeigandReader.start(w["d0"], w["d1"], w["type"])
            readers.append((w["label"], q, ev, t))

        while True:
            for label, q, _, _ in readers:
                while not q.empty():
                    data: CardData = q.get()
                    if data.is_valid and data.card_data is not None:
                        print(f"  [{label}] Карта: {data.card_data}")
                    else:
                        err = data.error_message or "неизвестная ошибка"
                        print(f"  [{label}] ✗ {err}")
            time.sleep(0.05)

    except KeyboardInterrupt:
        print("\n  Завершение Wiegand…")
    finally:
        for label, _, ev, t in readers:
            ev.clear()  # Сигнал потоку: остановись
            t.join(timeout=2)
            if t.is_alive():
                print(f"  ⚠ {label}: поток не завершился вовремя")
        print("  ✅ Wiegand потоки остановлены")


# ---------------------------------------------------------------------------
# Пункт 4 — Серийные порты
# ---------------------------------------------------------------------------

def serial_test() -> None:
    """
    Запустить чтение с серийных портов в фоновых потоках.

    Завершается по Ctrl+C.
    """
    readers = []
    try:
        for s in SER:
            print(f"  🔵 {s['label']}: {s['port']} @ {s['baud']}")
        print("     Нажмите Ctrl+C для возврата в меню.\n")

        for s in SER:
            rdr = BackgroundSerialReader(s["port"], s["baud"])
            q = rdr.start()
            readers.append((s["label"], q, rdr))

        while True:
            for label, q, _ in readers:
                while not q.empty():
                    msg = q.get()
                    print(f"  [{label}] {msg}")
            time.sleep(0.05)

    except KeyboardInterrupt:
        print("\n  Завершение Serial…")
    finally:
        for label, _, rdr in readers:
            rdr.stop()
        print("  ✅ Serial потоки остановлены")


# ---------------------------------------------------------------------------
# Пункт 5 — Прямой тест GPIO
# ---------------------------------------------------------------------------

def direct_gpio_test(ctrl: GpiodPinController, lock: threading.Lock) -> None:
    """
    Интерактивный прямой тест GPIO через GpiodPinController.

    Позволяет вручную выставлять и читать уровни пинов мультиплексора
    и сдвигового регистра, а также отправлять HEX-значения.

    Берёт общий лок перед каждой операцией с GPIO, чтобы не конфликтовать
    с фоновыми потоками MuxWorker и ShiftRegWorker.

    Parameters
    ----------
    ctrl : GpiodPinController
        Инициализированный контроллер (тот же, что используют воркеры).
    lock : threading.Lock
        Общий лок (``pct.lock``), предотвращающий одновременный доступ.
    """
    addr_pins = MUX["addr_pins"]
    input_pin = MUX["input_pin"]
    sd  = SR["ser_data"]
    clk = SR["ser_clk"]
    lat = SR["ser_latch"]

    print(f"\n{'─' * 60}")
    print("  ПРЯМОЙ ТЕСТ GPIO (gpiod)")
    print(f"  Адресные пины: {addr_pins}")
    print(f"  Вход мux:      {input_pin}")
    print(f"  SER_DATA={sd}  CLK={clk}  LATCH={lat}")
    print(f"{'─' * 60}")
    print("  Команды:")
    print("    snap          — снимок всех пинов")
    print("    set PIN 0|1   — установить пин (напр. set PA6 1)")
    print("    addr MASK     — выставить адрес мux (напр. addr 3 → A0=1 A1=1 A2=0)")
    print("    send HEX      — отправить в сдвиговый регистр (напр. send A5FF)")
    print("    0 | quit      — назад в меню")
    print(f"{'─' * 60}")

    while True:
        try:
            raw = input("  gpio> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not raw:
            continue

        parts = raw.split()
        cmd = parts[0].lower()

        if cmd in ("0", "quit", "q"):
            break

        elif cmd == "snap":
            # Снимок всех пинов — берём лок, чтобы не гонять с воркерами
            with lock:
                snap = ctrl.get_snapshot()
            print(f"  {'Пин':<8} Уровень")
            print(f"  {'─' * 16}")
            for pin, level in sorted(snap.items()):
                print(f"  {pin:<8} {level}")

        elif cmd == "set" and len(parts) == 3:
            pin_name = parts[1].upper()
            try:
                level = int(parts[2])
                if level not in (0, 1):
                    raise ValueError
            except ValueError:
                print("  ❌ Уровень должен быть 0 или 1")
                continue
            try:
                with lock:
                    ctrl.write_pin(pin_name, level)
                print(f"  {pin_name} → {'HIGH' if level else 'LOW'}")
            except ValueError as e:
                print(f"  ❌ {e}")

        elif cmd == "addr" and len(parts) == 2:
            try:
                mask = int(parts[1])
            except ValueError:
                print("  ❌ MASK должна быть числом (0..7)")
                continue
            n = len(addr_pins)
            values = {addr_pins[i]: (mask >> i) & 1 for i in range(n)}
            with lock:
                ctrl.set_outputs_bulk(values)
                snap = ctrl.get_snapshot()
            in_val = snap.get(input_pin, "?")
            bits_str = " ".join(str(v) for v in values.values())
            print(f"  Адрес {mask} [{bits_str}] → IN={in_val}")

        elif cmd == "send" and len(parts) == 2:
            try:
                val = int(parts[1], 16)
                bits_count = len(parts[1]) * 4
                if not (0 <= val <= 0xFFFF):
                    print("  ❌ Диапазон 0000-FFFF")
                    continue
            except ValueError:
                print("  ❌ Некорректный HEX")
                continue
            # Прямая отправка битов MSB-first — под локом, чтобы воркер
            # не переключил адресные пины в середине CLK-импульсов
            with lock:
                for i in range(bits_count - 1, -1, -1):
                    bit = (val >> i) & 1
                    ctrl.write_pin(sd, bit)
                    ctrl.write_pin(clk, 0)
                    ctrl.write_pin(clk, 1)
                    ctrl.write_pin(clk, 0)
                ctrl.write_pin(lat, 0)
                ctrl.write_pin(lat, 1)
                ctrl.write_pin(lat, 0)
            print(f"  ✅ 0x{val:04X} отправлено в сдвиговый регистр")

        else:
            print("  ❌ Неизвестная команда. Введите snap / set / addr / send / quit")

    print(f"{'─' * 60}\n")


# ---------------------------------------------------------------------------
# Точка входа
# ---------------------------------------------------------------------------

def main() -> None:
    """
    Главная функция: инициализация оборудования и цикл интерактивного меню.

    Последовательность инициализации
    ---------------------------------
    1. Создаём **один** ``GpiodPinController`` и захватываем все нужные линии.
    2. Создаём ``PinControllerThread``, передавая ему готовый контроллер
       и общий лок. Запускаем фоновые потоки (MuxWorker + ShiftRegWorker).
    3. Запускаем цикл меню. Прямой тест (пункт 5) работает с тем же
       контроллером под тем же локом.
    4. В блоке ``finally`` останавливаем потоки и закрываем контроллер.

    Один контроллер = один gpiod-request на набор линий.
    Нет EBUSY, нет дублирования захвата.
    """
    all_outputs = list(MUX["addr_pins"]) + [SR["ser_data"], SR["ser_clk"], SR["ser_latch"]]
    modes: dict = {MUX["input_pin"]: "input"}
    for p in all_outputs:
        modes[p] = "output"

    print("🔧 Инициализация GpiodPinController…")
    try:
        ctrl = GpiodPinController()
        ctrl.open(modes, pull_ups=[MUX["input_pin"]])
        ctrl.set_output_states(dict.fromkeys(all_outputs, 0))
    except Exception as e:
        print(f"❌ Ошибка инициализации GpiodPinController: {e}")
        print("   Убедитесь, что gpiod установлен и у вас есть доступ к /dev/gpiochip*")
        sys.exit(1)

    print("✅ GpiodPinController готов\n")

    # Фоновые потоки (MuxWorker + ShiftRegWorker) — используют тот же контроллер
    print("🔧 Запуск PinControllerThread…")
    pct = PinControllerThread(
        controller=ctrl,              # передаём единственный контроллер
        mux_input=MUX["input_pin"],
        mux_outputs=tuple(MUX["addr_pins"]),
        shift_ser_data=SR["ser_data"],
        shift_ser_clk=SR["ser_clk"],
        shift_ser_latch=SR["ser_latch"],
        shift_reg_len=SR["reg_len"],
    )

    try:
        pct.start()
    except Exception as e:
        print(f"❌ Ошибка запуска PinControllerThread: {e}")
        ctrl.close()
        sys.exit(1)

    print("✅ PinControllerThread запущен (MuxWorker + ShiftRegWorker)\n")

    try:
        while True:
            print_menu()
            choice = input("Выберите пункт: ").strip()

            if choice == "1":
                shift_reg_test(pct)
            elif choice == "2":
                mux_test(pct)
            elif choice == "3":
                wiegand_test()
            elif choice == "4":
                serial_test()
            elif choice == "5":
                # Передаём тот же лок, что используют воркеры
                direct_gpio_test(ctrl, pct.lock)
            elif choice == "0":
                print("Выход…")
                break
            else:
                print("❌ Неверный пункт. Введите 0–5.")

    except KeyboardInterrupt:
        print("\nВыход…")
    finally:
        # Сначала останавливаем фоновые потоки, потом закрываем контроллер
        pct.stop()
        ctrl.close()
        print("✅ Все ресурсы GPIO освобождены")


if __name__ == "__main__":
    main()
