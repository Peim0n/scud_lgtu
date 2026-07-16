"""Инфраструктура звука."""
from scud_lgtu.infrastructure.sound.player import SoundPlayer
from scud_lgtu.domain.ports import SoundOutput


class SoundOutputAdapter:
    """Adapter for SoundPlayer to implement SoundOutput."""
    
    def __init__(self, player: SoundPlayer):
        """Initialize adapter with player."""
        self._player = player
    
    def play(self, effect: str) -> None:
        """Play sound effect."""
        self._player.play_effect(effect)
