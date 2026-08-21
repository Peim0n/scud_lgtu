"""Тесты адаптера управления сетевым окружением."""
import json

import pytest

from app.infrastructure.network.network_manager import NetworkManagerAdapter, _run


class FakeProc:
    def __init__(self, returncode, stdout, stderr):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


@pytest.fixture
def manager():
    return NetworkManagerAdapter()


def test_run_success(monkeypatch):
    def fake_run(cmd, **kwargs):
        return FakeProc(0, "hello", "")

    monkeypatch.setattr("app.infrastructure.network.network_manager.subprocess.run", fake_run)
    rc, out, err = _run(["echo", "hello"])
    assert rc == 0
    assert out == "hello"


def test_run_command_not_found(monkeypatch):
    def fake_run(cmd, **kwargs):
        raise FileNotFoundError()

    monkeypatch.setattr("app.infrastructure.network.network_manager.subprocess.run", fake_run)
    rc, out, err = _run(["missing"])
    assert rc == 127


def test_get_hostname(monkeypatch, manager):
    monkeypatch.setattr("app.infrastructure.network.network_manager.subprocess.run", lambda cmd, **kw: FakeProc(0, "myhost\n", ""))
    assert manager.get_hostname() == "myhost"


def test_get_timezone(monkeypatch, manager):
    monkeypatch.setattr("app.infrastructure.network.network_manager.subprocess.run", lambda cmd, **kw: FakeProc(0, "Europe/Moscow\n", ""))
    assert manager.get_timezone() == "Europe/Moscow"


def test_list_interfaces_json(monkeypatch, manager):
    data = [
        {
            "ifname": "eth0",
            "operstate": "UP",
            "addr_info": [{"family": "inet", "local": "192.168.0.10"}],
        }
    ]
    monkeypatch.setattr("app.infrastructure.network.network_manager.subprocess.run", lambda cmd, **kw: FakeProc(0, json.dumps(data), ""))
    interfaces = manager.list_interfaces()
    assert len(interfaces) == 1
    assert interfaces[0]["name"] == "eth0"
    assert "192.168.0.10" in interfaces[0]["addresses"]


def test_apply_hostname(monkeypatch, manager):
    monkeypatch.setattr("app.infrastructure.network.network_manager.subprocess.run", lambda cmd, **kw: FakeProc(0, "", ""))
    result = manager.apply({"network": {"hostname": "newhost", "timezone": "", "ntp_servers": [], "ethernet": {}, "wifi": {}}})
    assert result["hostname"]["ok"] is True


def test_apply_static_requires_address(manager):
    result = manager.apply({"network": {"ethernet": {"interface": "eth0", "method": "static", "netmask": "255.255.255.0"}, "wifi": {}, "hostname": "", "timezone": "", "ntp_servers": []}})
    assert result["ethernet"]["ok"] is False


def test_netmask_to_cidr(manager):
    assert manager._netmask_to_cidr("255.255.255.0") == 24
    assert manager._netmask_to_cidr("255.255.0.0") == 16
    assert manager._netmask_to_cidr("bad") == 24
