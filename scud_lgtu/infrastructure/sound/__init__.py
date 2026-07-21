"""Инфраструктура звука."""
from scud_lgtu.infrastructure.sound.player import SoundPlayer
from scud_lgtu.domain.access.ports.ports import SoundOutput


class SoundOutputAdapter:
    """Адаптер SoundPlayer для реализации SoundOutput."""

    def __init__(self, player: SoundPlayer):
        """Инициализировать адаптер с плеером."""
        self._player = player

    def play(self, effect: str) -> None:
        """Воспроизвести звуковой эффект."""
        self._player.play_effect(effect)
