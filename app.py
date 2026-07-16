#!/usr/bin/env python3
"""
Главная точка входа микропрограммы контроллера турникета.

Реализует бизнес-логику СКУД по ТЗ:
- получение событий от считывателей / сенсоров через ScudEngine
- проверка идентификаторов по локальному кэшу
- управление исполнительными механизмами (турникет, реле)
- журналирование событий и синхронизация с бэкендом
"""

import logging
import time

from scud_lgtu.engine import ScudEngine
from scud_lgtu.access_controller import AccessController
from scud_lgtu.local_access_cache import LocalAccessCache
from scud_lgtu.config import load as load_config


def setup_logging(cfg: dict) -> None:
    """Настроить уровень и формат логирования из конфигурации."""
    log_cfg = cfg.get("logging", {})
    level = getattr(logging, log_cfg.get("level", "INFO").upper(), logging.INFO)
    fmt = log_cfg.get("format", "%(asctime)s %(name)s [%(levelname)s] %(message)s")
    logging.basicConfig(level=level, format=fmt)


def main() -> None:
    """Главная точка входа: загружает конфиг, запускает движок и API."""
    cfg = load_config()
    setup_logging(cfg)

    engine = ScudEngine()

    access_cfg = cfg.get("access", {})
    cache = LocalAccessCache(
        path="/home/danil/Git/scud_lgtu/local_access.json",
        static_key=access_cfg.get("static_key"),
        dynamic_key=access_cfg.get("dynamic_key"),
    )
    controller = AccessController(
        engine,
        cache=cache,
        timings=cfg.get("timings", {}),
    )

    api_cfg = cfg.get("api", {})
    if api_cfg.get("enabled", True):
        controller.enable_api(host=api_cfg.get("host", "0.0.0.0"), port=api_cfg.get("port", 8080))

    try:
        controller.start()
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logging.getLogger(__name__).info("Остановка по Ctrl+C")
    finally:
        controller.stop()


if __name__ == "__main__":
    main()
