"""
Обработчик событий прохода.

Обрабатывает события обнаружения прохода по датчикам.
Логирует проходы, управляет реле, отслеживает завершение проходов.
"""
from scud_lgtu.domain.events import PassageDetected
from scud_lgtu.domain.events import OutputCommandsGenerated
import logging
import asyncio

logger = logging.getLogger(__name__)


async def handle_passage_detected(event: PassageDetected, turnstile, passage_tracker, event_bus, event_log, devices: dict) -> None:
    """
    Обработать событие обнаружения прохода.

    Parameters
    ----------
    event : PassageDetected
        Событие обнаружения прохода
    turnstile : TurnstileState
        Состояние турникета для управления
    passage_tracker : PassageTracker
        Трекер проходов для отслеживания завершения
    event_bus : EventBus
        Шина событий для публикации команд
    event_log : EventLogAdapter
        Адаптер лога событий для записи проходов
    devices : dict
        Мапинг устройств из конфига

    Note
    ----
    Направления прохода:
    - "in": нормальный вход
    - "out": нормальный выход
    - "turnback": разворот (человек прошел и вернулся)
    - "blockage": заслон (оба датчика активны длительное время)
    """
    direction = event.direction
    zone = event.zone
    duration = event.duration

    logger.info(f"Проход: {zone}, направление={direction}, длительность={duration:.3f}s")

    # Получаем конфигурацию датчиков из devices
    sensors = devices.get("sensors", {})

    # Находим конфигурацию датчика по label
    sensor_config = None
    for sensor_name, sensor_cfg in sensors.items():
        if sensor_cfg.get("label") == zone:
            sensor_config = sensor_cfg
            break

    if not sensor_config:
        logger.error(f"Датчик не найден в конфиге: {zone}")
        return

    sensor_direction = sensor_config.get("direction", "entry")

    if direction == "blockage":
        # Заслон - держать реле открытым
        logger.warning(f"Заслон: {zone}, длительность={duration:.3f}s")

        # Логировать заслон
        event_log.log_passage(zone, "blockage", duration, result="blockage")

        # Держать реле открытым (не закрывать)
        # Реле уже открыто при проходе, просто не закрываем его
        return

    if direction == "turnback":
        # Разворот - закрыть реле
        logger.info(f"Разворот: {zone}, длительность={duration:.3f}s")

        # Логировать разворот
        event_log.log_passage(zone, "turnback", duration, result="turnback")

        # Закрыть реле
        await turnstile.close_async(event_bus)
        return

    # Нормальный проход (in/out)
    # Закрыть реле
    await turnstile.close_async(event_bus)

    # Логировать проход
    event_log.log_passage(zone, direction, duration, result="pass")

    # Отметить проход как завершённый в passage_tracker
    # Это позволит снова зайти с той же картой (но только если направление изменилось)
    if event.token:
        passage_tracker.mark_passed(event.token)
