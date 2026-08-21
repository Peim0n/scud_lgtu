"""Тесты модуля сетевого конфига."""
import os

import pytest

from app.infrastructure.network import defaults, load, save, update
from app.infrastructure.network import network_config as net_cfg


def test_load_missing_returns_empty(tmp_path):
    path = tmp_path / "config.yml"
    path.write_text("{}", encoding="utf-8")
    assert load(str(path)) == {}


def test_save_and_load_roundtrip(tmp_path):
    path = tmp_path / "config.yml"
    path.write_text("{}", encoding="utf-8")
    cfg = defaults()
    save(cfg, str(path))
    loaded = load(str(path))
    assert loaded == cfg
    assert (tmp_path / "network_config.yml").exists()


def test_update_merges(tmp_path):
    path = tmp_path / "config.yml"
    path.write_text("{}", encoding="utf-8")
    save(defaults(), str(path))
    result = update(str(path), {"network": {"hostname": "new-host"}})
    assert result["network"]["hostname"] == "new-host"
    assert result["network"]["ethernet"]["interface"] == "end0"


def test_env_override_path(tmp_path, monkeypatch):
    env_path = tmp_path / "net.yml"
    env_path.write_text("network:\n  hostname: env-host\n", encoding="utf-8")
    monkeypatch.setenv("LGTU_NETWORK_CONFIG", str(env_path))
    assert load(None)["network"]["hostname"] == "env-host"


def test_path_resolution(tmp_path):
    cfg_path = tmp_path / "config.yml"
    cfg_path.write_text("{}", encoding="utf-8")
    expected = tmp_path / "network_config.yml"
    assert net_cfg._network_config_path(str(cfg_path)) == str(expected)
