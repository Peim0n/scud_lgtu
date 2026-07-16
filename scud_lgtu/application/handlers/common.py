"""
Общие обработчики событий системы СКУД.

Этот модуль реализует общий обработчик для учётных данных (карты и QR-коды).
Обработчик проверяет доступ через AccessPolicy, отслеживает проход через PassageTracker
и управляет турникетом через TurnstileState. Использует конфигурацию устройств
для динамического определения индикаторов, биперов и направлений.

Функции
-------
- handle_credential_common: общий обработчик для учётных данных (карты и QR-коды)
"""
from scud_lgtu.domain.models import AuthSession
from scud_lgtu.domain.enums import DirectionEnum
import logging
import asyncio

logger = logging.getLogger(__name__)


async def handle_credential_common(event, turnstile, access_policy, passage_tracker, event_bus, session, devices: dict) -> None:
    """
    Общий обработчик для учётных данных (карты и QR-коды).

    Parameters
    ----------
    event : CardRead or QrRead
        Событие считывания учётных данных
    turnstile : TurnstileState
        Состояние турникета для управления
    access_policy : AccessPolicy
        Политика доступа для проверки разрешений
    passage_tracker : PassageTracker
        Трекер проходов для предотвращения двойных проходов
    event_bus : EventBus
        Шина событий для публикации команд
    session : AuthSession
        Сессия авторизации с токеном
    devices : dict
        Мапинг устройств из конфига
    """
    logger.debug(f"Обработка события учётных данных: {event}")

    # reader_id теперь логическое имя устройства (entry_reader, exit_reader, qr_reader)
    reader_id = event.reader_id
    readers = devices.get("readers", {})

    # Находим конфигурацию считывателя по логическому имени
    reader_config = readers.get(reader_id)

    if not reader_config:
        logger.error(f"Считыватель не найден в конфиге: {reader_id}")
        return

    # Получаем индикаторы, бипер и направление из конфига
    indicator_success = reader_config.get("indicator_success", "w1_green")
    indicator_fail = reader_config.get("indicator_fail", "w1_red")
    direction = reader_config.get("direction", "entry")

    # Проверка доступа
    decision = access_policy.check(event.credential)
    logger.debug(f"Результат проверки доступа: {decision}")

    if decision.allowed:
        # Обновляем user_id в сессии
        session.user_id = decision.user_id

        # Отслеживание прохода
        passage_tracker.track(session)

        # Открытие турникета через background task (таймер запускается сразу)
        if direction == "entry":
            asyncio.create_task(turnstile.open_entry_async(event_bus, start_timer=True))
        else:
            asyncio.create_task(turnstile.open_exit_async(event_bus, start_timer=True))
        logger.debug(f"Открытие турникета через async task (direction={direction})")

        # Включить зеленый индикатор на configured duration
        asyncio.create_task(turnstile.set_indicator_async(event_bus, indicator_success, True, turnstile._indicator_duration))
    else:
        # Отказ в доступе - последовательность писков через background task
        asyncio.create_task(turnstile.deny_beep_sequence(event_bus))
        logger.debug(f"Отказ в доступе, запущена последовательность писков")

        # Включить красный индикатор на configured duration
        asyncio.create_task(turnstile.set_indicator_async(event_bus, indicator_fail, True, turnstile._indicator_duration))
