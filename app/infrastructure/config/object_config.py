"""
Управление объектным конфигом — секции access, qr_decoder, backend.

Эти настройки относятся к конкретной точке доступа / контроллеру, а не к
базовой аппаратной конфигурации. Они вынесены в отдельный файл
``object_config.yml`` (рядом с ``config.yml``) и перекрывают значения из
основного конфига. Редактирование доступно через CLI и в перспективе —
через веб-интерфейс администрирования.
"""
from __future__ import annotations

import json
import os
from typing import Any

import yaml

from app.infrastructure.config.config_loader import _deep_merge

_EDITABLE_TOP_KEYS = {"access", "qr_decoder", "backend", "device", "web"}


def _object_config_path(config_path: str) -> str:
    """Путь к object_config.yml в той же директории, что и config.yml."""
    return os.path.join(os.path.dirname(os.path.abspath(config_path)), "object_config.yml")


def load(config_path: str) -> dict[str, Any]:
    """Загрузить объектный конфиг, если он существует."""
    path = _object_config_path(config_path)
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data if data is not None else {}


def save(config: dict[str, Any], config_path: str) -> None:
    """Сохранить объектный конфиг."""
    path = _object_config_path(config_path)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(config, f, allow_unicode=True, sort_keys=False, indent=2)


def is_editable_path(dotted_path: str) -> bool:
    """Разрешено ли редактировать указанный dotted-путь через CLI/веб."""
    if not dotted_path:
        return False
    top = dotted_path.split(".")[0]
    return top in _EDITABLE_TOP_KEYS


def _navigate(
    config: dict[str, Any],
    dotted_path: str,
    *,
    create: bool = False,
) -> tuple[dict[str, Any], str]:
    """Дойти по пути до родительского dict и вернуть (parent, last_key)."""
    keys = dotted_path.split(".")
    if not keys:
        raise ValueError("пустой путь")
    cur = config
    for key in keys[:-1]:
        if key not in cur:
            if create:
                cur[key] = {}
            else:
                raise KeyError(dotted_path)
        cur = cur[key]
        if not isinstance(cur, dict):
            raise TypeError(f"путь {dotted_path} проходит через не-dict")
    return cur, keys[-1]


def get(config: dict[str, Any], dotted_path: str) -> Any:
    """Получить значение по dotted-пути."""
    parent, last = _navigate(config, dotted_path)
    if last not in parent:
        raise KeyError(dotted_path)
    return parent[last]


def set_value(config: dict[str, Any], dotted_path: str, value: Any) -> None:
    """Установить значение по dotted-пути (создаёт промежуточные dict)."""
    if not is_editable_path(dotted_path):
        raise ValueError(
            f"путь '{dotted_path}' не относится к редактируемым секциям "
            f"({_EDITABLE_TOP_KEYS})"
        )
    parent, last = _navigate(config, dotted_path, create=True)
    parent[last] = value


def parse_typed_value(raw: str) -> Any:
    """Преобразовать строку из CLI в типизированное значение."""
    raw = raw.strip()

    if raw.lower() in {"null", "none", "~"}:
        return None
    if raw.lower() in {"true", "yes", "on"}:
        return True
    if raw.lower() in {"false", "no", "off"}:
        return False

    try:
        return int(raw)
    except ValueError:
        pass

    try:
        return float(raw)
    except ValueError:
        pass

    if (raw.startswith("{") and raw.endswith("}")) or (
        raw.startswith("[") and raw.endswith("]")
    ):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass

    return raw


def merge_with_base(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Объединить базовый конфиг и объектный override."""
    return _deep_merge(base, override)
