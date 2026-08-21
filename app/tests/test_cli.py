"""
Тесты CLI-диспетчера app/interfaces/cli.py (аргументы -> нужная cmd_*-функция, вывод).

Сами cmd_* функции (реальная работа с CertificateManager) уже покрыты
test_certificate_manager.py — здесь проверяем только "проводку" argparse
для группы команд ``cert`` (группа ``engine`` поднимает GPIO и в юнит-тестах
не проверяется).
"""
import json

from app.interfaces import cli


def test_cert_status_dispatch(monkeypatch, capsys):
    called = {}

    def fake_status(config_path):
        called["config_path"] = config_path
        return {"has_working_certificate": True}

    monkeypatch.setattr(cli, "cmd_cert_status", fake_status)

    exit_code = cli.main(["--config", "/tmp/x.yml", "cert", "status"])

    assert exit_code == 0
    assert called["config_path"] == "/tmp/x.yml"
    out = capsys.readouterr().out
    assert "has_working_certificate: True" in out


def test_cert_status_json_output(monkeypatch, capsys):
    monkeypatch.setattr(cli, "cmd_cert_status", lambda config_path: {"has_working_certificate": False})

    exit_code = cli.main(["--json", "cert", "status"])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert json.loads(out) == {"has_working_certificate": False}


def test_cert_status_error_sets_nonzero_exit(monkeypatch, capsys):
    monkeypatch.setattr(cli, "cmd_cert_status", lambda config_path: {"error": "boom"})

    exit_code = cli.main(["cert", "status"])

    assert exit_code == 1
    out = capsys.readouterr().out
    assert "Ошибка: boom" in out


def test_cert_import_initial_dispatch(monkeypatch):
    called = {}

    def fake_import(config_path, cert_file, key_file):
        called.update(config_path=config_path, cert_file=cert_file, key_file=key_file)
        return {"status": "ok"}

    monkeypatch.setattr(cli, "cmd_cert_import_initial", fake_import)

    exit_code = cli.main(["cert", "import-initial", "cert.pem", "key.pem"])

    assert exit_code == 0
    assert called == {"config_path": None, "cert_file": "cert.pem", "key_file": "key.pem"}


def test_cert_bootstrap_dispatch(monkeypatch):
    called = {}

    def fake_bootstrap(config_path):
        called["ran"] = True
        return {"status": "ok"}

    monkeypatch.setattr(cli, "cmd_cert_bootstrap", fake_bootstrap)

    exit_code = cli.main(["cert", "bootstrap"])

    assert exit_code == 0
    assert called == {"ran": True}


def test_cert_rotate_dispatch_with_force(monkeypatch):
    called = {}

    def fake_rotate(config_path, force):
        called.update(config_path=config_path, force=force)
        return {"rotated": True}

    monkeypatch.setattr(cli, "cmd_cert_rotate", fake_rotate)

    exit_code = cli.main(["cert", "rotate", "--force"])

    assert exit_code == 0
    assert called == {"config_path": None, "force": True}


def test_cert_rotate_dispatch_without_force(monkeypatch):
    called = {}

    def fake_rotate(config_path, force):
        called.update(config_path=config_path, force=force)
        return {"rotated": False}

    monkeypatch.setattr(cli, "cmd_cert_rotate", fake_rotate)

    cli.main(["cert", "rotate"])

    assert called == {"config_path": None, "force": False}


def test_no_command_prints_usage_and_exits():
    try:
        cli.main([])
    except SystemExit as exc:
        assert exc.code != 0
    else:
        raise AssertionError("argparse должен был завершить процесс из-за required=True")


def test_settings_get_dispatch(monkeypatch, capsys):
    called = {}

    def fake_get(config_path, key):
        called.update(config_path=config_path, key=key)
        return {"value": 42}

    monkeypatch.setattr(cli, "cmd_settings_get", fake_get)

    exit_code = cli.main(["--config", "/tmp/x.yml", "settings", "get", "backend.access_point_id"])

    assert exit_code == 0
    assert called == {"config_path": "/tmp/x.yml", "key": "backend.access_point_id"}
    assert "42" in capsys.readouterr().out


def test_settings_set_dispatch(monkeypatch, capsys):
    called = {}

    def fake_set(config_path, key, value):
        called.update(config_path=config_path, key=key, value=value)
        return {"status": "ok", "path": key, "value": 42}

    monkeypatch.setattr(cli, "cmd_settings_set", fake_set)

    exit_code = cli.main(["settings", "set", "backend.access_point_id", "42"])

    assert exit_code == 0
    assert called == {"config_path": None, "key": "backend.access_point_id", "value": "42"}
    out = capsys.readouterr().out
    assert "ok" in out or "42" in out


def test_settings_show_dispatch(monkeypatch, capsys):
    monkeypatch.setattr(cli, "cmd_settings_show", lambda config_path: {"config": {"x": 1}})

    exit_code = cli.main(["settings", "show"])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "x" in out


def test_settings_error_sets_nonzero_exit(monkeypatch, capsys):
    monkeypatch.setattr(cli, "cmd_settings_get", lambda config_path, key: {"error": "boom"})

    exit_code = cli.main(["settings", "get", "backend.access_point_id"])

    assert exit_code == 1
    assert "Ошибка: boom" in capsys.readouterr().out
