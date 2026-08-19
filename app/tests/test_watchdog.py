"""
Тесты Watchdog (infrastructure/engine.py): не перезапускает мёртвые потоки
(осознанное решение), но обязан явно и без спама сообщить об этом —
один раз на CRITICAL плюс событие в очередь (которое дальше уходит в
системный журнал событий, п. 5.5 ТЗ, и до бэкенда, §6.5 ресурс event).
"""
import queue
import threading
import time

from app.infrastructure.engine import EventSource, EventType, Watchdog


class _DeadThread:
    """Заглушка потока, который всегда 'мёртв'."""
    def is_alive(self):
        return False


class _AliveThread:
    def is_alive(self):
        return True


def test_dead_thread_reported_once_not_spammed(caplog):
    threads = {"gpio": _DeadThread()}
    event_queue = queue.Queue()
    stop_event = threading.Event()
    wd = Watchdog(threads, event_queue, stop_event, check_interval=0.01, stop_timeout=1.0)

    with caplog.at_level("CRITICAL"):
        wd.start()
        time.sleep(0.1)  # несколько проверок должны успеть пройти
        wd.stop()

    critical_records = [r for r in caplog.records if r.levelno >= 50 and "gpio" in r.message]
    assert len(critical_records) == 1, "должно быть ровно одно CRITICAL-сообщение, а не спам на каждой проверке"


def test_dead_thread_publishes_error_event_once():
    threads = {"wiegand": _DeadThread()}
    event_queue = queue.Queue()
    stop_event = threading.Event()
    wd = Watchdog(threads, event_queue, stop_event, check_interval=0.01, stop_timeout=1.0)

    wd.start()
    time.sleep(0.1)
    wd.stop()

    events = []
    while not event_queue.empty():
        events.append(event_queue.get_nowait())

    assert len(events) == 1
    assert events[0].type == EventType.ERROR.value
    assert events[0].source == EventSource.WATCHDOG.value
    assert events[0].payload["thread"] == "wiegand"


def test_thread_coming_back_alive_resets_report_flag():
    thread_ref = {"t": _DeadThread()}
    threads = {"serial": thread_ref["t"]}
    event_queue = queue.Queue()
    stop_event = threading.Event()
    wd = Watchdog(threads, event_queue, stop_event, check_interval=0.01, stop_timeout=1.0)

    wd.start()
    time.sleep(0.05)
    # Поток "оживает"
    threads["serial"] = _AliveThread()
    time.sleep(0.05)
    # И снова "умирает" - должно сообщиться заново.
    threads["serial"] = _DeadThread()
    time.sleep(0.05)
    wd.stop()

    events = []
    while not event_queue.empty():
        events.append(event_queue.get_nowait())

    assert len(events) == 2  # одно сообщение на каждую "смерть"


def test_alive_thread_never_reported():
    threads = {"mux": _AliveThread()}
    event_queue = queue.Queue()
    stop_event = threading.Event()
    wd = Watchdog(threads, event_queue, stop_event, check_interval=0.01, stop_timeout=1.0)

    wd.start()
    time.sleep(0.05)
    wd.stop()

    assert event_queue.empty()
