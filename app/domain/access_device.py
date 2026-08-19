"""Базовый класс для устройств контроля доступа (турникет, калитка, дверь и т.д.).

Этот модуль предоставляет общий интерфейс и логику для всех устройств доступа,
независимо от конкретной реализации оборудования.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class AccessDevice(ABC):
    """Базовый класс для устройств контроля доступа.

    Определяет общий интерфейс, который должны реализовать все устройства
    (турникет, калитка, дверь). Конкретные классы устройств обрабатывают
    свою специфичную FSM и маппинг выходов.
    """

    def __init__(self, device_id: str, timings: dict, resolver: Any):
        self._device_id = device_id
        self._resolver = resolver
        self._locked = False
        self._load_config(timings)

    @property
    def device_id(self) -> str:
        return self._device_id

    @property
    @abstractmethod
    def current_state_label(self) -> str:
        """Текущее состояние FSM устройства."""

    @property
    @abstractmethod
    def is_alarm_active(self) -> bool:
        """Активна ли пожарная тревога."""

    @property
    def locked(self) -> bool:
        """Заблокировано ли устройство админом."""
        return self._locked

    @locked.setter
    def locked(self, value: bool) -> None:
        self._locked = value

    @abstractmethod
    def handle(self, event) -> Any | None:
        """Обработать доменное событие и вернуть команду."""

    def _load_config(self, timings: dict) -> None:
        """Загрузить тайминги устройства и маппинги IO."""
        self._relay_timeout = self._resolver.get_timing(
            "devices", f"{self._device_id}.relay_open_duration_s",
            timings.get("relay_open_duration_s", 7.0)
        )
        self._button_timeout = self._resolver.get_timing(
            "devices", f"{self._device_id}.button_timer_duration_s",
            timings.get("button_timer_duration_s", 7.0)
        )
        self._indicator_duration = self._resolver.get_timing(
            "devices", f"{self._device_id}.indicator_duration_s",
            timings.get("indicator_duration_s", 2.0)
        )
        self._deny_beep_count = int(self._resolver.get_timing(
            "devices", f"{self._device_id}.deny_beep_count",
            timings.get("deny_beep_count", 3)
        ))
        self._deny_beep_duration = self._resolver.get_timing(
            "devices", f"{self._device_id}.deny_beep_duration_s",
            timings.get("deny_beep_duration_s", 0.1)
        )
        self._deny_beep_pause = self._resolver.get_timing(
            "devices", f"{self._device_id}.deny_beep_pause_s",
            timings.get("deny_beep_pause_s", 0.1)
        )
        self._alarm_beep_on_duration = self._resolver.get_timing(
            "devices", f"{self._device_id}.alarm_beep_on_duration_s",
            timings.get("alarm_beep_on_duration_s", 0.5)
        )
        self._alarm_beep_off_duration = self._resolver.get_timing(
            "devices", f"{self._device_id}.alarm_beep_off_duration_s",
            timings.get("alarm_beep_off_duration_s", 0.5)
        )
        self._open_beep_duration = self._resolver.get_timing(
            "devices", f"{self._device_id}.open_beep_duration_s",
            timings.get("open_beep_duration_s", 0.2)
        )

        # Загрузить маппинги IO из секции конфигурации устройства
        self._resolver.set_context(f"devices.{self._device_id}")
        self._load_io_mappings()

    @abstractmethod
    def _load_io_mappings(self) -> None:
        """Загрузить маппинги пинов/реле устройства."""
