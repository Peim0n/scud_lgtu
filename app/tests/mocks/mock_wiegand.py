"""Мок wiegand пакета app.tests.mocks."""
from collections.abc import Callable
from dataclasses import dataclass


@dataclass
class CardData:
    """Мок данных карты."""
    facility_code: int
    card_number: int
    bits: int
    timestamp: float


class MockWiegandReader:
    """Мок Wiegand-считывателя, имитирующий поведение gpiod."""

    def __init__(
        self,
        d0_pin: str,
        d1_pin: str,
        format_type: str = "era_mf_64_hash",
        bit_timeout: float = 0.025,
        wait_timeout: float = 0.005,
        max_bits: int = 64
    ):
        """Инициализировать мок Wiegand-считывателя."""
        self.d0_pin = d0_pin
        self.d1_pin = d1_pin
        self.format_type = format_type
        self.bit_timeout = bit_timeout
        self.wait_timeout = wait_timeout
        self.max_bits = max_bits

        self._card_callback: Callable | None = None

    def set_card_callback(self, callback: Callable) -> None:
        """Установить callback для событий карты."""
        self._card_callback = callback

    def start(self) -> None:
        """Запустить считыватель (no-op для мока)."""

    def stop(self) -> None:
        """Остановить считыватель (no-op для мока)."""

    def inject_card(self, card_number: int, facility_code: int = 1) -> None:
        """Внедрить событие чтения карты для тестирования."""
        import time
        card_data = CardData(
            facility_code=facility_code,
            card_number=card_number,
            bits=26,  # Standard 26-bit Wiegand
            timestamp=time.time()
        )

        if self._card_callback:
            self._card_callback(card_data)

    def is_running(self) -> bool:
        """Проверить, запущен ли считыватель (для мока всегда True)."""
        return True
