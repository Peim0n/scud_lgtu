"""Тесты веб-интерфейса администрирования."""
import base64
import os

import pytest

from app.interfaces.web.server import create_app


def _auth_header():
    creds = base64.b64encode(b"admin:admin").decode()
    return {"Authorization": f"Basic {creds}"}


@pytest.fixture
def client(tmp_path):
    cfg_path = tmp_path / "config.yml"
    cfg_path.write_text(
        "device:\n"
        "  type: turnstile\n"
        "backend:\n"
        "  base_url: https://example.com\n"
        "  access_point_id: 1\n"
        "  verify_hostname: false\n"
        "  user_agent: OldUA/1.0\n"
        "access:\n"
        "  static_key: aabbcc\n"
        "qr_decoder:\n"
        "  base_url: https://qr.example/?\n",
        encoding="utf-8",
    )
    (tmp_path / "object_config.yml").write_text("{}", encoding="utf-8")
    # Изолируем network_config.yml
    os.environ["LGTU_NETWORK_CONFIG"] = str(tmp_path / "network_config.yml")
    app = create_app(str(cfg_path))
    app.testing = True
    with app.test_client() as c:
        yield c
    os.environ.pop("LGTU_NETWORK_CONFIG", None)


def test_index_requires_auth(client):
    resp = client.get("/")
    assert resp.status_code == 401


def test_index_with_auth(client):
    resp = client.get("/", headers=_auth_header())
    assert resp.status_code == 200
    assert b"IS SCUD Admin" in resp.data


def test_network_page_renders_form(client):
    resp = client.get("/network", headers=_auth_header())
    assert resp.status_code == 200
    assert b"ethernet_interface" in resp.data


def test_network_save(client):
    resp = client.post(
        "/network/save",
        headers=_auth_header(),
        data={
            "hostname": "test-host",
            "timezone": "UTC",
            "ntp_servers": "0.pool.ntp.org\n1.pool.ntp.org",
            "ethernet_interface": "eth0",
            "ethernet_method": "static",
            "ethernet_address": "192.168.1.10",
            "ethernet_netmask": "255.255.255.0",
            "ethernet_gateway": "192.168.1.1",
            "ethernet_dns": "8.8.8.8, 8.8.4.4",
            "wifi_enabled": "off",
            "wifi_interface": "wlan0",
            "wifi_ssid": "",
            "wifi_password": "",
            "wifi_method": "dhcp",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "Сетевые настройки сохранены".encode() in resp.data


def test_backend_page_renders_form(client):
    resp = client.get("/backend", headers=_auth_header())
    assert resp.status_code == 200
    assert b"backend.base_url" in resp.data


def test_backend_save_updates_object_config(client):
    resp = client.post(
        "/backend/save",
        headers=_auth_header(),
        data={
            "backend.base_url": "https://new.example.com",
            "backend.access_point_id": "42",
            "backend.verify_hostname": "on",
            "backend.user_agent": "TestUA/1.0",
            "qr_decoder.base_url": "https://new.qr/?",
            "access.static_key": "0011223344",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "Объектный конфиг сохран".encode() in resp.data

    # Проверим, что object_config.yml обновился
    from app.infrastructure.config import object_config as obj_cfg
    override = obj_cfg.load(client.application.config["config_path"])
    assert override["backend"]["base_url"] == "https://new.example.com"
    assert override["backend"]["access_point_id"] == 42
    assert override["backend"]["verify_hostname"] is True
    assert override["qr_decoder"]["base_url"] == "https://new.qr/?"
    assert override["access"]["static_key"] == "0011223344"


def test_backend_save_device_type(client):
    resp = client.post(
        "/backend/save",
        headers=_auth_header(),
        data={"device.type": "gate"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    from app.infrastructure.config import object_config as obj_cfg
    override = obj_cfg.load(client.application.config["config_path"])
    assert override["device"]["type"] == "gate"


def test_network_apply_reports_result(monkeypatch, client):
    from app.infrastructure.network import defaults, save as save_network
    save_network(defaults(), client.application.config["config_path"])

    monkeypatch.setattr(
        "app.interfaces.web.server.NetworkManagerAdapter",
        lambda: type("FakeNM", (), {
            "get_hostname": lambda self: "h",
            "get_timezone": lambda self: "UTC",
            "list_interfaces": lambda self: [],
            "apply": lambda self, cfg: {"ok": True, "hostname": {"ok": True}},
        })(),
    )
    resp = client.post("/network/apply", headers=_auth_header(), follow_redirects=True)
    assert resp.status_code == 200
    assert "Сетевые настройки применены".encode() in resp.data


def test_cli_web_dispatch(monkeypatch):
    from app.interfaces import cli
    called = {}

    def fake_web(config_path, host, port, debug):
        called.update(config_path=config_path, host=host, port=port, debug=debug)
        return 0

    monkeypatch.setattr(cli, "cmd_web", fake_web)
    exit_code = cli.main(["--config", "/tmp/x.yml", "web", "--host", "127.0.0.1", "--port", "9000", "--debug"])
    assert exit_code == 0
    assert called == {"config_path": "/tmp/x.yml", "host": "127.0.0.1", "port": 9000, "debug": True}


def test_cli_web_disabled(monkeypatch, tmp_path):
    """Если web.enabled = false, команда web завершается с ошибкой."""
    from app.interfaces import cli

    cfg_path = tmp_path / "config.yml"
    cfg_path.write_text("web:\n  enabled: false\n", encoding="utf-8")
    (tmp_path / "object_config.yml").write_text("web:\n  enabled: false\n", encoding="utf-8")

    exit_code = cli.main(["--config", str(cfg_path), "web"])
    assert exit_code == 1


def test_auth_page_renders(client):
    resp = client.get("/auth", headers=_auth_header())
    assert resp.status_code == 200
    assert "Учётные данные".encode() in resp.data


def test_auth_save_changes_credentials(client):
    resp = client.post(
        "/auth/save",
        headers=_auth_header(),
        data={"username": "newadmin", "new_password": "secret123", "confirm_password": "secret123"},
    )
    assert resp.status_code == 302

    # Старые учётные данные больше не работают
    resp = client.get("/", headers=_auth_header())
    assert resp.status_code == 401

    # Новые работают
    new_creds = base64.b64encode(b"newadmin:secret123").decode()
    resp = client.get("/", headers={"Authorization": f"Basic {new_creds}"})
    assert resp.status_code == 200


def test_auth_save_rejects_mismatched_passwords(client):
    resp = client.post(
        "/auth/save",
        headers=_auth_header(),
        data={"username": "admin", "new_password": "pass1", "confirm_password": "pass2"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "Пароли не совпадают".encode() in resp.data


def test_cert_page_renders(client, monkeypatch):
    monkeypatch.setattr(
        "app.interfaces.cli.cmd_cert_status",
        lambda cfg_path: {
            "has_working_certificate": True,
            "has_initial_certificate": False,
            "rotation_threshold_fraction": 0.5,
            "rotation_retry_interval_days": 1.0,
            "not_before": "2026-01-01T00:00:00+00:00",
            "not_after": "2026-04-01T00:00:00+00:00",
            "total_lifetime_days": 90.0,
            "remaining_days": 45.0,
            "remaining_fraction": 0.5,
            "due_for_rotation": False,
        },
    )
    resp = client.get("/cert", headers=_auth_header())
    assert resp.status_code == 200
    assert "mTLS".encode() in resp.data
    assert "установлен и активен".encode() in resp.data


def test_cert_bootstrap_dispatch(client, monkeypatch):
    monkeypatch.setattr(
        "app.interfaces.cli.cmd_cert_bootstrap",
        lambda cfg_path: {"has_working_certificate": True},
    )
    resp = client.post("/cert/bootstrap", headers=_auth_header())
    assert resp.status_code == 302


def test_cert_rotate_dispatch(client, monkeypatch):
    monkeypatch.setattr(
        "app.interfaces.cli.cmd_cert_rotate",
        lambda cfg_path, force: {"rotated": True},
    )
    resp = client.post("/cert/rotate", headers=_auth_header(), data={"force": "on"})
    assert resp.status_code == 302


def test_cert_import_no_files(client):
    resp = client.post("/cert/import", headers=_auth_header(), follow_redirects=True)
    assert resp.status_code == 200
    assert "Нужно выбрать оба файла".encode() in resp.data
