"""Обработчик событий QR-кодов."""
from scud_lgtu.domain.events import QrRead
from scud_lgtu.domain.models import AuthSession
from scud_lgtu.domain.enums import DirectionEnum, TokenTypeEnum


def handle_qr_read(event: QrRead, turnstile, access_policy, passage_tracker) -> None:
    """Обработать событие считывания QR-кода."""
    # Проверка доступа
    decision = access_policy.check(event.credential)
    
    if decision.allowed:
        # Создание сессии авторизации
        session = AuthSession(
            token=f"maxid:{event.credential.value}",
            direction=DirectionEnum.IN,
            user_id=decision.user_id
        )
        
        # Отслеживание прохода
        passage_tracker.track(session)
        
        # Открытие турникета
        commands = turnstile.open_entry()
        # Применение команд через исполнительный механизм (для реализации)
    else:
        # Отказ в доступе
        commands = turnstile.block()
        # Применение команд через исполнительный механизм (для реализации)
