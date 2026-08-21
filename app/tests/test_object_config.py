"""Тесты объектного конфига (object_config.yml) и CLI настроек."""
import json

import pytest

from app.infrastructure.config import load
from app.infrastructure.config import object_config as obj_cfg


def test_object_config_overrides_base_config(tmp_path):
    """object_config.yml перекрывает значения из config.yml."""
    config_path = tmp_path / "config.yml"
    config_path.write_text(
        "backend:\n"
        "  base_url: https://old.example.com\n"
        "  timeout: 5\n"
        "access:\n"
        "  static_key: aabbcc\n",
        encoding="utf-8",
    )
    override_path = tmp_path / "object_config.yml"
    override_path.write_text(
        "backend:\n  base_url: https://new.example.com\n", encoding="utf-8",
    )

    merged = load(str(config_path))

    assert merged["backend"]["base_url"] == "https://new.example.com"
    assert merged["backend"]["timeout"] == 5
    assert merged["access"]["static_key"] == "aabbcc"


def test_object_config_missing_is_ok(tmp_path):
    """Отсутствие object_config.yml не ломает загрузку."""
    config_path = tmp_path / "config.yml"
    config_path.write_text("backend:\n  base_url: https://example.com\n", encoding="utf-8")

    merged = load(str(config_path))

    assert merged["backend"]["base_url"] == "https://example.com"


def test_object_config_load_save_roundtrip(tmp_path):
    """Сохранение и загрузка object_config.yml."""
    config_path = tmp_path / "config.yml"
    config_path.write_text("access:\n  static_key: x\n", encoding="utf-8")

    override = {
        "backend": {
            "access_point_id": 7,
            "verify_hostname": False,
        },
        "qr_decoder": {"base_url": "https://qr.example/?"},
    }
    obj_cfg.save(override, str(config_path))
    loaded = obj_cfg.load(str(config_path))

    assert loaded == override


def test_object_config_path_resolution(tmp_path):
    """Путь к object_config вычисляется рядом с config.yml."""
    config_path = tmp_path / "config.yml"
    config_path.write_text("{}", encoding="utf-8")
    expected = tmp_path / "object_config.yml"
    assert obj_cfg.load(str(config_path)) == {}
    # load не создаёт файл; сохраним и проверим
    obj_cfg.save({"access": {"static_key": "00"}}, str(config_path))
    assert expected.exists()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("42", 42),
        ("3.14", 3.14),
        ("true", True),
        ("True", True),
        ("yes", True),
        ("false", False),
        ("no", False),
        ("null", None),
        ("None", None),
        ("~", None),
        ("hello", "hello"),
        ('{"a": 1}', {"a": 1}),
        ("[1, 2, 3]", [1, 2, 3]),
    ],
)
def test_parse_typed_value(raw, expected):
    assert obj_cfg.parse_typed_value(raw) == expected


def test_get_and_set_value():
    config = {
        "backend": {"base_url": "https://example.com", "nested": {"x": 1}},
        "access": {"static_key": "aa"},
    }

    assert obj_cfg.get(config, "backend.base_url") == "https://example.com"
    assert obj_cfg.get(config, "backend.nested.x") == 1

    obj_cfg.set_value(config, "backend.access_point_id", 42)
    assert config["backend"]["access_point_id"] == 42

    with pytest.raises(KeyError):
        obj_cfg.get(config, "backend.missing")


def test_set_value_rejects_non_editable_section():
    config = {"timings": {"x": 1}}
    with pytest.raises(ValueError):
        obj_cfg.set_value(config, "timings.x", 2)

    with pytest.raises(ValueError):
        obj_cfg.set_value(config, "unknown.key", "value")


def test_get_nonexistent_key_raises():
    config = {"backend": {"base_url": "https://example.com"}}
    with pytest.raises(KeyError):
        obj_cfg.get(config, "backend.missing")


# ---------------------------------------------------------------------------
# CLI: реальная работа с файлами
# ---------------------------------------------------------------------------


def test_cli_settings_get_and_set(tmp_path):
    """settings get/set меняет только object_config.yml, не трогая config.yml."""
    from app.interfaces.cli import cmd_settings_get, cmd_settings_set

    config_path = tmp_path / "config.yml"
    config_path.write_text(
        "backend:\n"
        "  base_url: https://base.example.com\n"
        "  access_point_id: 1\n",
        encoding="utf-8",
    )
    (tmp_path / "object_config.yml").write_text("{}", encoding="utf-8")

    assert cmd_settings_get(str(config_path), "backend.access_point_id") == {"value": 1}

    result = cmd_settings_set(str(config_path), "backend.access_point_id", "99")
    assert result == {"status": "ok", "path": "backend.access_point_id", "value": 99}

    assert cmd_settings_get(str(config_path), "backend.access_point_id") == {"value": 99}

    # config.yml не изменился
    base_cfg = load(str(config_path))
    assert base_cfg["backend"]["access_point_id"] == 99  # merged
    # Но в самом config.yml осталось старое значение
    import yaml
    with open(config_path, "r", encoding="utf-8") as f:
        raw_base = yaml.safe_load(f)
    assert raw_base["backend"]["access_point_id"] == 1


def test_cli_settings_set_rejects_unknown_key(tmp_path):
    from app.interfaces.cli import cmd_settings_set

    config_path = tmp_path / "config.yml"
    config_path.write_text("backend:\n  base_url: https://example.com\n", encoding="utf-8")

    result = cmd_settings_set(str(config_path), "backend.missing_key", "42")
    assert "error" in result


def test_cli_settings_show_empty(tmp_path):
    from app.interfaces.cli import cmd_settings_show

    config_path = tmp_path / "config.yml"
    config_path.write_text("{}", encoding="utf-8")
    assert cmd_settings_show(str(config_path)) == {"config": {}}
