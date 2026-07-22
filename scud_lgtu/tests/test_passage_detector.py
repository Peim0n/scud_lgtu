"""Тесты односенсорного детектора прохода."""
from queue import Queue

from scud_lgtu.infrastructure.persistence.passage_detector import PassageDetector


def _detector():
    queue = Queue()
    detector = PassageDetector(
        zone_label="zone1",
        inner_name="sensor_1",
        outer_name="sensor_2",
        event_queue=queue,
        passage_timeout=2.0,
        blockage_timeout=5.0,
    )
    return detector, queue


def test_entry_open_accepts_only_entry_sensor():
    detector, queue = _detector()
    detector.arm("in")

    detector.on_mux_state({"sensor_1": 1, "sensor_2": 0}, 1.0)
    detector.on_mux_state({"sensor_1": 1, "sensor_2": 1}, 2.0)
    assert queue.empty()

    detector.on_mux_state({"sensor_1": 0, "sensor_2": 1}, 3.0)
    detector.on_mux_state({"sensor_1": 1, "sensor_2": 1}, 4.0)
    event = queue.get_nowait()
    assert event.payload["direction"] == "in"


def test_exit_open_accepts_only_exit_sensor():
    detector, queue = _detector()
    detector.arm("out")

    detector.on_mux_state({"sensor_1": 0, "sensor_2": 1}, 1.0)
    detector.on_mux_state({"sensor_1": 1, "sensor_2": 1}, 2.0)
    assert queue.empty()

    detector.on_mux_state({"sensor_1": 1, "sensor_2": 0}, 3.0)
    detector.on_mux_state({"sensor_1": 1, "sensor_2": 1}, 4.0)
    event = queue.get_nowait()
    assert event.payload["direction"] == "out"
