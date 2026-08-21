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
