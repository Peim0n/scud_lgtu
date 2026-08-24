"""
Модуль загрузки конфигурации из config.yml.

Преобразует addr_pins из словаря {A0: offset, A1: offset, ...}
в упорядоченный список offsets и сохраняет метки addr_labels.
"""

import copy
import os

import yaml


# Секции конфигурации, относящиеся к конкретному объекту/контроллеру,
# и потому вынесенные в отдельный object_config.yml (перекрывает config.yml).
_EDITABLE_TOP_KEYS = {"access", "qr_decoder", "backend"}


def _object_config_path(config_path: str) -> str:
    """Путь к объектному конфигу: /etc/scud_lgtu/ или рядом с config.yml."""
    runtime_dir = "/etc/scud_lgtu"
    if os.path.isdir(runtime_dir):
        return os.path.join(runtime_dir, "object_config.yml")
    return os.path.join(os.path.dirname(os.path.abspath(config_path)), "object_config.yml")


def _load_raw(config_path: str) -> dict:
    """Прочитать YAML-файл как dict (без мержа и нормализации)."""
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    return cfg if cfg is not None else {}


def resolve_config_path(config_path: str | None = None) -> str:
    """Вернуть абсолютный путь к config.yml, если путь не задан."""
    if config_path is not None:
        return os.path.abspath(config_path)
    return os.path.join(os.path.dirname(__file__), "..", "..", "config.yml")


def _deep_merge(base: dict, override: dict) -> dict:
    """Рекурсивно объединить override в копию base."""
    result = copy.deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def load(config_path: str | None = None) -> dict:
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
    config_path = resolve_config_path(config_path)

    cfg = _load_raw(config_path)

    # Поддержка наследования от базового конфига
    extends = cfg.pop("extends", None)
    if extends:
        if not os.path.isabs(extends):
            extends = os.path.join(os.path.dirname(config_path), extends)
        base_cfg = load(extends)
        cfg = _deep_merge(base_cfg, cfg)

    # Объектный конфиг (access/qr_decoder/backend) перекрывает базовый
    override_path = _object_config_path(config_path)
    if os.path.exists(override_path):
        override = _load_raw(override_path)
        cfg = _deep_merge(cfg, override)

    # Нормализуем addr_pins: dict -> list, отсортированный по ключу (A0 < A1 < A2 ...)
    mux = cfg.get("mux", {})
    addr_dict = mux.get("addr_pins", {})
    if isinstance(addr_dict, dict):
        sorted_keys = sorted(addr_dict.keys())
        mux["addr_pins"] = [addr_dict[k] for k in sorted_keys]
        mux["addr_labels"] = sorted_keys
    cfg["mux"] = mux

    return cfg
