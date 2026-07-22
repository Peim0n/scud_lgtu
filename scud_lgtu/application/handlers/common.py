"""
Общие обработчики событий системы СКУД.

Синхронный обработчик для учётных данных (карты и QR-коды).
"""
from scud_lgtu.domain.common.models.models import AuthSession
from scud_lgtu.domain.common.enums.enums import DirectionEnum
from scud_lgtu.domain.common.events.events import OutputCommandsGenerated
import logging

logger = logging.getLogger(__name__)


def handle_credential_common(event, turnstile, access_policy, passage_tracker, event_bus, session, devices: dict) -> None:
    """Общий обработчик для учётных данных (карты и QR-коды)."""
    logger.debug(f"Обработка события учётных данных: {event}")

    reader_id = event.reader_id
    readers = devices.get("readers", {})
    reader_config = readers.get(reader_id)

    if not reader_config:
        logger.error(f"Считыватель не найден в конфиге: {reader_id}")
        return

    indicator_success = reader_config.get("indicator_success")
    indicator_fail = reader_config.get("indicator_fail")
    direction = reader_config.get("direction")

    if not indicator_success or not indicator_fail or not direction:
        logger.error(f"Неполная конфигурация считывателя: {reader_id}")
        return

    decision = access_policy.check(event.credential)
    logger.info(f"Результат проверки доступа: allowed={decision.allowed}, reason={decision.reason}, user_id={decision.user_id}")

    commands = []
    if decision.allowed:
        session.user_id = decision.user_id
        direction_enum = DirectionEnum.IN if direction == "entry" else DirectionEnum.OUT

        turnstile.set_current_session(session.token, session.user_id)

        if direction == "entry":
            commands.extend(turnstile.open_entry(start_timer=True))
        else:
            commands.extend(turnstile.open_exit(start_timer=True))

        commands.extend(turnstile.set_indicator(indicator_success, True, turnstile.indicator_duration))
        logger.info(f"Доступ разрешён: открытие {direction}")
    else:
        logger.info(f"Отказ в доступе: {decision.reason}")
        commands.extend(turnstile.deny_beep())
        if indicator_fail:
            commands.extend(turnstile.set_indicator(indicator_fail, True, turnstile.indicator_duration))

    if commands:
        event_bus.publish(OutputCommandsGenerated(commands=commands))
