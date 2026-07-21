"""
Обработчик событий прохода системы СКУД.

Этот модуль реализует обработчик событий обнаружения прохода по датчикам. Обработчик
логирует проходы, управляет реле турникета и отслеживает завершение проходов через
PassageTracker. Поддерживает различные направления прохода: нормальный вход (in),
нормальный выход (out), разворот (turnback) и заслон (blockage). Использует конфигурацию
устройств для динамического определения направления датчика.

Функции
-------
- handle_passage_detected: обработать событие обнаружения прохода
"""
from scud_lgtu.domain.common.events.events import PassageDetected, PassageStarted, PassageSensorsCleared, OutputCommandsGenerated
from scud_lgtu.domain.common.models.models import Passage
from scud_lgtu.domain.common.enums.enums import ResultEnum, DirectionEnum
import logging
import asyncio

logger = logging.getLogger(__name__)


async def handle_passage_detected(event: PassageDetected, turnstile, passage_tracker, event_bus, passage_service, devices: dict) -> None:
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
    passage_service : PassageService
        Сервис для записи проходов
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

    # Получаем конфигурацию зон прохода из devices
    passage_zones = devices.get("passage_zones", {})

    # Находим конфигурацию зоны по label
    zone_config = None
    for zone_cfg in passage_zones:
        if zone_cfg.get("label") == zone:
            zone_config = zone_cfg
            break

    if not zone_config:
        logger.error(f"Зона прохода не найдена в конфиге: {zone}")
        return

    def _log_passage(result: ResultEnum, direction_enum: DirectionEnum = DirectionEnum.IN):
        passage = Passage(
            direction=direction_enum,
            zone=zone,
            duration=duration,
            result=result,
            token=event.token,
            user_id=event.user_id,
        )
        passage_service.log_passage(passage)

    if direction == "blockage":
        logger.warning(f"Заслон: {zone}, длительность={duration:.3f}s")
        _log_passage(ResultEnum.BLOCKAGE)
        turnstile.hold_open()
        return

    # Снять удержание открытым по датчикам — таймер автозакрытия снова работает
    turnstile.release_open()

    if direction == "turnback":
        logger.info(f"Разворот: {zone}, длительность={duration:.3f}s")
        _log_passage(ResultEnum.TURNBACK)
        await turnstile.close_async(event_bus)
        return

    # Нормальный проход (in/out)
    await turnstile.close_async(event_bus)
    direction_enum = DirectionEnum.IN if direction == "in" else DirectionEnum.OUT
    _log_passage(ResultEnum.PASS, direction_enum)

    # Отметить токен как использованный для любого исхода (проход, разворот, заслон),
    # чтобы повторный вход по той же карте был запрещён до выхода.
    if event.token:
        passage_tracker.mark_passed(event.token)


def handle_passage_started(event: PassageStarted, turnstile) -> None:
    """Обработать начало прохода (первый датчик сработал)."""
    logger.debug(f"Passage started: {event.zone} direction={event.direction}")
    turnstile.hold_open()


async def handle_passage_cleared(event: PassageSensorsCleared, turnstile, event_bus) -> None:
    """Обработать освобождение датчиков после заслона — закрыть турникет."""
    safety = getattr(turnstile, "_post_blockage_safety", 1.0)
    logger.info(f"Passage sensors cleared: {event.zone}, safety hold {safety}s")
    turnstile.hold_open(duration=safety)
