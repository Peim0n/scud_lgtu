"""Базовые классы команд устройства доступа.

Команда — самодостаточная корутина, которая управляет выходами через
исполнителя (`CommandRunner`), ждёт таймаута или сигнала остановки и
при необходимости возвращает список `OutputCommand` для очистки.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from app.domain.models import OutputCommand


@dataclass(frozen=True)
class CommandMeta:
    """Метаданные команды для исполнителя."""
    name: str
    conflicts: tuple[str, ...] = ()
    state_label: str | None = None
    end_state_label: str | None = None


class Command:
    """Базовая команда устройства."""
    meta = CommandMeta("base")

    def __init__(self) -> None:
        self._stop = asyncio.Event()

    def request_stop(self) -> None:
        """Сигнал команде завершить работу. Вызывается исполнителем."""
        self._stop.set()

    async def _sleep(self, timeout: float) -> bool:
        """Спать timeout секунд или до сигнала остановки.

        Возвращает True, если была запрошена остановка.
        """
        if timeout <= 0:
            return self._stop.is_set()
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False

    async def _wait_until_stopped(self) -> None:
        await self._stop.wait()

    async def run(self, executor: Any) -> None:
        """Выполнить команду. Корутина завершается самостоятельно."""
        raise NotImplementedError

    def cleanup(self) -> list[OutputCommand]:
        """Запасной вариант выключения, если команду отменили насильно."""
        return []

    def refresh(self) -> None:
        """Обновить таймер команды без повторного выполнения."""
