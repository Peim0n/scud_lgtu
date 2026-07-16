"""
Модуль загрузки конфигурации из config.yml.

Преобразует addr_pins из словаря {A0: offset, A1: offset, ...}
в упорядоченный список offsets и сохраняет метки addr_labels.
"""

import os
import yaml

# Путь к config.yml — ищем в родительской папке (рядом с корнем проекта)
_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.yml")


def load() -> dict:
    """
    Загрузить и нормализовать конфигурацию из config.yml.

    Returns
    -------
    dict
        Словарь конфигурации. В секции ``mux`` поле ``addr_pins``
        преобразуется из ``{A0: val, A1: val, ...}`` в список значений,
        отсортированных по ключам, а метки сохраняются в ``addr_labels``.
    """
    with open(_CONFIG_PATH, "r") as f:
        cfg = yaml.safe_load(f)

    # Нормализуем addr_pins: dict -> list, отсортированный по ключу (A0 < A1 < A2 ...)
    mux = cfg.get("mux", {})
    addr_dict = mux.get("addr_pins", {})
    if isinstance(addr_dict, dict):
        sorted_keys = sorted(addr_dict.keys())
        mux["addr_pins"] = [addr_dict[k] for k in sorted_keys]
        mux["addr_labels"] = sorted_keys
    cfg["mux"] = mux

    return cfg
