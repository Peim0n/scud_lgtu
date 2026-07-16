"""
Заглушка бизнес-логики для ScudEngine.

Показывает, как принимать события из `event_queue` и отправлять команды.
Реальная бизнес-логика заменит этот файл.
"""

import logging
import queue

from .engine import ScudEngine
from .events import ScudCommand, CommandTarget, CommandAction, EventType

logger = logging.getLogger(__name__)


def run_business_logic(engine: ScudEngine) -> None:
    """
    Пример цикла обработки событий.

    Читает события из ``engine.get_event_queue()`` и печатает их.
    При получении карты из Wiegand-1 отправляет тестовую команду
    на сдвиговый регистр.
    """
    events = engine.get_event_queue()

    while True:
        try:
            event = events.get(timeout=1.0)
        except queue.Empty:
            continue

        if event.type == EventType.CARD_READ:
            card = event.payload.get("card_data")
            reader = event.payload.get("reader")
            valid = event.payload.get("is_valid", False)
            logger.info("[BL] Карта от %s: %s (valid=%s)", reader, card, valid)

            # Пример реакции: мигнуть сдвиговым регистром
            if valid and reader == "wiegand_Wiegand-1":
                engine.send_command(
                    ScudCommand(
                        target=CommandTarget.SHIFT,
                        action=CommandAction.WRITE_SHIFT,
                        payload={"value": 0xA5A5},
                    )
                )

        elif event.type == EventType.MUX_CHANGED:
            logger.debug("[BL] MUX изменился: %s", event.payload)

        elif event.type == EventType.SERIAL_DATA:
            logger.info("[BL] Serial %s: %s", event.payload.get("reader"), event.payload.get("data"))

        elif event.type == EventType.ERROR:
            logger.error("[BL] Ошибка от %s: %s", event.source, event.payload)

        elif event.type == EventType.STOP:
            logger.info("[BL] Получена команда остановки")
            break


def main() -> None:
    """Запустить ScudEngine и бизнес-логику в одном потоке."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(name)s [%(levelname)s] %(message)s",
    )

    engine = ScudEngine()
    try:
        engine.start()
        run_business_logic(engine)
    except KeyboardInterrupt:
        logger.info("Остановка по Ctrl+C")
    finally:
        engine.stop()


if __name__ == "__main__":
    main()
