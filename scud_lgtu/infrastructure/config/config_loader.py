"""
Модуль загрузки конфигурации из config.yml.

Преобразует addr_pins из словаря {A0: offset, A1: offset, ...}
в упорядоченный список offsets и сохраняет метки addr_labels.
"""

import os
import copy
from typing import Any

import yaml


def _deep_merge(base: dict, override: dict) -> dict:
    """Рекурсивно объединить override в копию base."""
    result = copy.deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def load(config_path: str = None) -> dict:
    """
    Загрузить и нормализовать конфигурацию из config.yml.

    Parameters
    ----------
    config_path : str, optional
        Путь к файлу конфигурации. Если не указан, используется
        config.yml в директории модуля.

    Returns
    -------
    dict
        Словарь конфигурации. В секции ``mux`` поле ``addr_pins``
        преобразуется из ``{A0: val, A1: val, ...}`` в список значений,
        отсортированных по ключам, а метки сохраняются в ``addr_labels``.
    """
    if config_path is None:
        config_path = os.path.join(os.path.dirname(__file__), "..", "..", "config.yml")

    with open(config_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    if cfg is None:
        cfg = {}

    # Поддержка наследования от базового конфига
    extends = cfg.pop("extends", None)
    if extends:
        if not os.path.isabs(extends):
            extends = os.path.join(os.path.dirname(config_path), extends)
        base_cfg = load(extends)
        cfg = _deep_merge(base_cfg, cfg)

    # Нормализуем addr_pins: dict -> list, отсортированный по ключу (A0 < A1 < A2 ...)
    mux = cfg.get("mux", {})
    addr_dict = mux.get("addr_pins", {})
    if isinstance(addr_dict, dict):
        sorted_keys = sorted(addr_dict.keys())
        mux["addr_pins"] = [addr_dict[k] for k in sorted_keys]
        mux["addr_labels"] = sorted_keys
    cfg["mux"] = mux

    return cfg
