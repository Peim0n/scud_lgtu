"""Простой веб-интерфейс администрирования контроллера.

Запускается как отдельный сервис (без GPIO), позволяет менять:
- параметры бэкенда/доступа/QR (object_config.yml);
- сетевые настройки (network_config.yml + применение через nmcli и пр.).

Аутентификация: HTTP Basic Auth, по умолчанию admin / admin.
"""
from __future__ import annotations

import functools
import logging
import os
from typing import Any

from flask import (
    Flask,
    Response,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)

from app.infrastructure.config import load as load_config, resolve_config_path
from app.infrastructure.config import object_config as obj_cfg
from app.infrastructure.network import defaults as network_defaults, load as load_network, save as save_network
from app.infrastructure.network.network_manager import NetworkManagerAdapter
from app.interfaces.web.auth_config import check as check_auth, load as load_auth, save as save_auth
from app.interfaces.web.field_labels import DESCRIPTIONS, HIDDEN_FIELDS, LABELS
from app.infrastructure.devices.device_factory import available_device_types

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


def _check_auth(username: str, password: str) -> bool:
    cfg_path = _config_path(current_app)
    return check_auth(username, password, cfg_path)


def _authenticate() -> Response:
    return Response(
        "Необходима авторизация",
        401,
        {"WWW-Authenticate": 'Basic realm="LGTU Controller"'},
    )


def require_auth(view: Any) -> Any:
    @functools.wraps(view)
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        auth = request.authorization
        if not auth or not _check_auth(auth.username, auth.password):
            return _authenticate()
        return view(*args, **kwargs)

    return wrapped


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def _load_or_create_secret_key(config_path: str) -> str:
    """Загрузить SECRET_KEY из файла или сгенерировать новый.

    Файл: /etc/scud_lgtu/web_secret.key (на проде) или рядом с config.yml.
    При первом запуске генерируется случайный ключ и сохраняется.
    """
    runtime_dir = "/etc/scud_lgtu"
    if os.path.isdir(runtime_dir):
        secret_path = os.path.join(runtime_dir, "web_secret.key")
    else:
        secret_path = os.path.join(os.path.dirname(os.path.abspath(config_path)), "web_secret.key")

    if os.path.exists(secret_path):
        with open(secret_path, "r", encoding="utf-8") as f:
            key = f.read().strip()
            if key:
                return key

    # Генерируем новый ключ
    import secrets as _secrets
    key = _secrets.token_hex(32)
    try:
        with open(secret_path, "w", encoding="utf-8") as f:
            f.write(key)
        os.chmod(secret_path, 0o600)
    except OSError:
        # Read-only ФС или нет прав — используем сгенерированный ключ в памяти
        # (будет новый при каждом перезапуске, flash-сообщения не переживут)
        pass
    return key


def create_app(config_path: str | None = None) -> Flask:
    """Создать Flask-приложение."""
    app = Flask(
        __name__,
        template_folder=os.path.join(os.path.dirname(__file__), "templates"),
        static_folder=os.path.join(os.path.dirname(__file__), "static"),
    )
    resolved = resolve_config_path(config_path)
    app.config["config_path"] = resolved
    # SECRET_KEY: из env (продакшн override) или из файла (генерится при первом запуске)
    app.config["SECRET_KEY"] = os.environ.get("LGTU_WEB_SECRET") or _load_or_create_secret_key(resolved)

    _register_routes(app)
    return app


def _config_path(app: Flask) -> str:
    return app.config["config_path"]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


def _register_routes(app: Flask) -> None:
    app.route("/")(require_auth(index))
    app.route("/network")(require_auth(network_page))
    app.route("/network/save", methods=["POST"])(require_auth(network_save))
    app.route("/network/apply", methods=["POST"])(require_auth(network_apply))
    app.route("/backend")(require_auth(backend_page))
    app.route("/backend/save", methods=["POST"])(require_auth(backend_save))
    app.route("/auth")(require_auth(auth_page))
    app.route("/auth/save", methods=["POST"])(require_auth(auth_save))
    app.route("/cert")(require_auth(cert_page))
    app.route("/cert/bootstrap", methods=["POST"])(require_auth(cert_bootstrap))
    app.route("/cert/import", methods=["POST"])(require_auth(cert_import))
    app.route("/cert/rotate", methods=["POST"])(require_auth(cert_rotate))
    app.route("/cert/reset", methods=["POST"])(require_auth(cert_reset))
    app.route("/cert/exchange", methods=["POST"])(require_auth(cert_exchange))
    app.route("/restart-service", methods=["POST"])(require_auth(restart_service))
    app.route("/reboot", methods=["POST"])(require_auth(reboot_device))


def index() -> str:
    """Главная страница / дашборд."""
    cfg_path = _config_path(current_app)
    merged = load_config(cfg_path)
    net_cfg = load_network(cfg_path)
    nm = NetworkManagerAdapter()
    status = {
        "hostname": nm.get_hostname(),
        "timezone": nm.get_timezone(),
        "interfaces": nm.list_interfaces(),
        "backend": merged.get("backend", {}),
    }
    return render_template("index.html", status=status, net_cfg=net_cfg)


def network_page() -> str:
    """Страница редактирования сетевых настроек."""
    cfg_path = _config_path(current_app)
    net_cfg = load_network(cfg_path) or network_defaults()
    nm = NetworkManagerAdapter()
    current = {
        "hostname": nm.get_hostname(),
        "timezone": nm.get_timezone(),
        "interfaces": nm.list_interfaces(),
        "ntp": nm.get_ntp_status(),
    }
    # Всегда берём реальные имена интерфейсов из системы — поле readonly
    detected_eth = nm.detect_ethernet_interface()
    detected_wifi = nm.detect_wifi_interface()
    if detected_eth:
        net_cfg.setdefault("network", {}).setdefault("ethernet", {})["interface"] = detected_eth
    if detected_wifi:
        net_cfg.setdefault("network", {}).setdefault("wifi", {})["interface"] = detected_wifi
    # Если конфиг пустой (нет network_config.yml), берём системные hostname/timezone как стартовые
    if not net_cfg.get("network", {}).get("hostname") and current["hostname"]:
        net_cfg["network"]["hostname"] = current["hostname"]
    if not net_cfg.get("network", {}).get("timezone") and current["timezone"]:
        net_cfg["network"]["timezone"] = current["timezone"]

    # Текущие системные адреса для интерфейсов — показываем в серых полях при DHCP
    iface_by_name = {i["name"]: i for i in current["interfaces"]}
    eth_iface = iface_by_name.get(net_cfg["network"]["ethernet"]["interface"], {})
    wifi_iface = iface_by_name.get(net_cfg["network"]["wifi"].get("interface", ""), {})

    available_timezones = _list_timezones()
    return render_template(
        "network.html", cfg=net_cfg, current=current, timezones=available_timezones,
        eth_current=eth_iface, wifi_current=wifi_iface,
    )


def network_save() -> Any:
    """Сохранить сетевой конфиг из формы."""
    cfg_path = _config_path(current_app)
    updates = _parse_network_form(request.form)
    # Если пароль Wi-Fi пустой — не затираем существующий
    wifi_password = updates.get("network", {}).get("wifi", {}).get("password", "")
    if not wifi_password:
        existing = load_network(cfg_path) or {}
        existing_pwd = existing.get("network", {}).get("wifi", {}).get("password", "")
        if existing_pwd:
            updates["network"]["wifi"]["password"] = existing_pwd
    load_network(cfg_path)  # гарантируем, что файл существует/не мешает
    save_network(updates, cfg_path)
    flash("Сетевые настройки сохранены.", "success")
    return redirect(url_for("network_page"))


def network_apply() -> Any:
    """Применить сохранённые сетевые настройки к системе."""
    cfg_path = _config_path(current_app)
    net_cfg = load_network(cfg_path)
    if not net_cfg:
        flash("Сетевой конфиг пуст.", "error")
        return redirect(url_for("network_page"))

    nm = NetworkManagerAdapter()
    result = nm.apply(net_cfg)
    logger.info("network_apply result: %s", result)
    if result.get("ok"):
        flash("Сетевые настройки применены.", "success")
    else:
        failed = []
        for k, v in result.items():
            if isinstance(v, dict) and not v.get("ok"):
                failed.append(f"{k}: {v.get('message', 'неизвестная ошибка')}")
        flash(f"Ошибка применения: {'; '.join(failed)}", "error")
    return redirect(url_for("network_page"))


def backend_page() -> str:
    """Страница редактирования backend/доступа/QR."""
    cfg_path = _config_path(current_app)
    merged = load_config(cfg_path)
    override = obj_cfg.load(cfg_path)
    return render_template("backend.html", merged=merged, override=override, labels=LABELS, descriptions=DESCRIPTIONS, device_types=available_device_types(), hidden_fields=HIDDEN_FIELDS)


def backend_save() -> Any:
    """Сохранить изменения в object_config.yml."""
    cfg_path = _config_path(current_app)
    merged = load_config(cfg_path)
    override = obj_cfg.load(cfg_path)

    # Собираем все поля формы, относящиеся к редактируемым секциям
    for dotted_path, raw_value in request.form.items():
        if not obj_cfg.is_editable_path(dotted_path):
            continue
        # backend.cert.* — не редактируется, КРОМЕ backend.cert.subject.*
        if dotted_path.startswith("backend.cert.") and not dotted_path.startswith("backend.cert.subject."):
            continue
        # Скрытые инфраструктурные поля
        if dotted_path in HIDDEN_FIELDS:
            continue
        try:
            current_value = obj_cfg.get(merged, dotted_path)
            parsed = _parse_backend_value(raw_value, current_value)
            obj_cfg.set_value(override, dotted_path, parsed)
        except (KeyError, ValueError) as exc:
            logger.warning("Пропуск поля %s: %s", dotted_path, exc)

    obj_cfg.save(override, cfg_path)
    flash("Настройки сохранены. Нажмите «Применить настройки» для активации.", "success")
    return redirect(url_for("backend_page"))


# ---------------------------------------------------------------------------
# Restart scud_lgtu service
# ---------------------------------------------------------------------------


def restart_service() -> Any:
    """Перезапустить systemd-сервис scud_lgtu (применить настройки)."""
    import subprocess
    try:
        result = subprocess.run(
            ["systemctl", "restart", "scud_lgtu"],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0:
            flash("Настройки применены. Контроллер перезапущен.", "success")
        else:
            flash(f"Ошибка применения: {result.stderr or result.stdout}", "error")
    except Exception as exc:
        flash(f"Ошибка применения: {exc}", "error")
    return redirect(url_for("backend_page"))


def reboot_device() -> Any:
    """Перезагрузить устройство (systemctl reboot)."""
    import subprocess
    # Проверка пароля — дополнительная защита от случайного ребута
    password = request.form.get("reboot_password", "")
    cfg_path = _config_path(current_app)
    creds = load_auth(cfg_path)
    if not check_auth(creds["username"], password, cfg_path):
        flash("Неверный пароль. Перезагрузка отменена.", "error")
        return redirect(url_for("index"))
    try:
        # Запускаем reboot в фоне — ответ успеет уйти клиенту
        subprocess.Popen(["systemctl", "reboot"])
        flash("Устройство перезагружается. Подождите ~1 минуту.", "success")
    except Exception as exc:
        flash(f"Ошибка перезагрузки: {exc}", "error")
    return redirect(url_for("index"))


# ---------------------------------------------------------------------------
# Cert: управление mTLS-сертификатом (KMS или загрузка файла)
# ---------------------------------------------------------------------------


def cert_page() -> str:
    """Страница управления сертификатом."""
    from app.interfaces.cli import cmd_cert_status
    cfg_path = _config_path(current_app)
    status = cmd_cert_status(cfg_path)
    return render_template("cert.html", status=status)


def cert_bootstrap() -> Any:
    """Выполнить первичный обмен через KMS."""
    from app.interfaces.cli import cmd_cert_bootstrap as do_bootstrap
    cfg_path = _config_path(current_app)
    result = do_bootstrap(cfg_path)
    if "error" in result:
        flash(f"Ошибка: {result['error']}", "error")
    else:
        flash("Первичный обмен выполнен через KMS.", "success")
    return redirect(url_for("cert_page"))


def cert_import() -> Any:
    """Импортировать первичный сертификат/ключ из загруженных файлов."""
    from app.interfaces.cli import cmd_cert_import_initial
    cfg_path = _config_path(current_app)

    cert_file = request.files.get("cert_file")
    key_file = request.files.get("key_file")
    if not cert_file or not key_file:
        flash("Нужно выбрать оба файла: сертификат и ключ.", "error")
        return redirect(url_for("cert_page"))

    try:
        cert_pem = cert_file.read().decode("utf-8")
        key_pem = key_file.read().decode("utf-8")
    except UnicodeDecodeError:
        flash("Файлы должны быть в текстовом формате PEM.", "error")
        return redirect(url_for("cert_page"))

    # Сохраняем во временные файлы и переиспользуем cmd_cert_import_initial
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        cert_path = os.path.join(tmpdir, "cert.pem")
        key_path = os.path.join(tmpdir, "key.pem")
        with open(cert_path, "w", encoding="utf-8") as f:
            f.write(cert_pem)
        with open(key_path, "w", encoding="utf-8") as f:
            f.write(key_pem)
        result = cmd_cert_import_initial(cfg_path, cert_path, key_path)

    if "error" in result:
        flash(f"Ошибка: {result['error']}", "error")
    else:
        flash("Первичный сертификат импортирован. Теперь выполните обмен через KMS.", "success")
    return redirect(url_for("cert_page"))


def cert_rotate() -> Any:
    """Принудительная ротация рабочего сертификата."""
    from app.interfaces.cli import cmd_cert_rotate as do_rotate
    cfg_path = _config_path(current_app)
    force = request.form.get("force") == "on"
    result = do_rotate(cfg_path, force)
    if "error" in result:
        flash(f"Ошибка: {result['error']}", "error")
    elif result.get("rotated"):
        fp = result.get("fingerprint_sha256", "")
        fp_short = fp[:16] if fp else ""
        flash(f"Сертификат ротирован. Новый fingerprint: {fp_short}…", "success")
    elif force:
        flash("Принудительная ротация не удалась — проверьте логи.", "error")
    else:
        flash("Ротация не требуется (порог не достигнут).", "info")
    return redirect(url_for("cert_page"))


def cert_reset() -> Any:
    """Удалить рабочий сертификат (полный сброс)."""
    cfg_path = _config_path(current_app)
    config = load_config(cfg_path)
    base_dir = os.path.dirname(os.path.abspath(cfg_path))
    cert_cfg = config.get("backend", {}).get("cert", {})
    # Сертификаты в /etc/scud_lgtu/certs/ на проде, рядом с config.yml — в dev
    runtime_dir = "/etc/scud_lgtu"
    if os.path.isdir(runtime_dir):
        cert_dir = os.path.join(runtime_dir, "certs")
    else:
        cert_dir = os.path.join(base_dir, cert_cfg.get("cert_dir", "infrastructure/certs"))

    removed = []
    for name in ("working_cert.pem", "working_key.pem"):
        path = os.path.join(cert_dir, name)
        if os.path.exists(path):
            os.remove(path)
            removed.append(name)

    if removed:
        flash(f"Удалены: {', '.join(removed)}. Сертификаты сброшены.", "success")
    else:
        flash("Сертификатов не найдено — нечего удалять.", "info")
    return redirect(url_for("cert_page"))


def cert_exchange() -> Any:
    """Обменять первичный сертификат на рабочий через бэкенд (без KMS)."""
    from app.interfaces.cli import cmd_cert_bootstrap as do_bootstrap
    cfg_path = _config_path(current_app)
    result = do_bootstrap(cfg_path)
    if "error" in result:
        flash(f"Ошибка: {result['error']}", "error")
    else:
        fp = result.get("fingerprint_sha256", "")
        fp_short = fp[:16] if fp else ""
        flash(f"Рабочий сертификат получен. Fingerprint: {fp_short}…", "success")
    return redirect(url_for("cert_page"))


# ---------------------------------------------------------------------------
# Auth: смена логина/пароля
# ---------------------------------------------------------------------------


def auth_page() -> str:
    """Страница смены учётных данных."""
    cfg_path = _config_path(current_app)
    creds = load_auth(cfg_path)
    return render_template("auth.html", username=creds["username"])


def auth_save() -> Any:
    """Сохранить новые логин/пароль."""
    cfg_path = _config_path(current_app)
    username = request.form.get("username", "").strip()
    old_password = request.form.get("old_password", "")
    new_password = request.form.get("new_password", "")
    confirm_password = request.form.get("confirm_password", "")

    if not username:
        flash("Логин не может быть пустым.", "error")
        return redirect(url_for("auth_page"))
    if not check_auth(load_auth(cfg_path)["username"], old_password, cfg_path):
        flash("Неверный текущий пароль.", "error")
        return redirect(url_for("auth_page"))
    if not new_password:
        flash("Пароль не может быть пустым.", "error")
        return redirect(url_for("auth_page"))
    if new_password != confirm_password:
        flash("Пароли не совпадают.", "error")
        return redirect(url_for("auth_page"))

    save_auth(username, new_password, cfg_path)
    flash("Учётные данные обновлены. При следующем входе используйте новый логин/пароль.", "success")
    return redirect(url_for("auth_page"))


# ---------------------------------------------------------------------------
# Form parsing
# ---------------------------------------------------------------------------


def _parse_backend_value(raw_value: str, current_value: Any) -> Any:
    """Преобразовать значение из HTML-формы с учётом текущего типа."""
    if isinstance(current_value, bool):
        return raw_value.strip().lower() in {"true", "on", "yes", "1"}
    if isinstance(current_value, list):
        return [s.strip() for s in raw_value.splitlines() if s.strip()]
    if isinstance(current_value, str):
        return raw_value
    if current_value is None and raw_value.strip().lower() in {"null", "none", "~"}:
        return None
    return obj_cfg.parse_typed_value(raw_value)


def _parse_network_form(form: Any) -> dict[str, Any]:
    """Преобразовать request.form в структуру network_config."""
    eth_dns = [s.strip() for s in form.get("ethernet_dns", "").split(",") if s.strip()]
    wifi_dns = [s.strip() for s in form.get("wifi_dns", "").split(",") if s.strip()]
    ntp_servers = [s.strip() for s in form.get("ntp_servers", "").splitlines() if s.strip()]

    return {
        "network": {
            "hostname": form.get("hostname", "").strip(),
            "timezone": form.get("timezone", "").strip(),
            "ntp_servers": ntp_servers,
            "ethernet": {
                "interface": form.get("ethernet_interface", "eth0").strip(),
                "method": form.get("ethernet_method", "dhcp").strip(),
                "address": form.get("ethernet_address", "").strip(),
                "netmask": form.get("ethernet_netmask", "").strip(),
                "gateway": form.get("ethernet_gateway", "").strip(),
                "dns": eth_dns,
            },
            "wifi": {
                "enabled": form.get("wifi_enabled") == "on",
                "interface": form.get("wifi_interface", "wlan0").strip(),
                "ssid": form.get("wifi_ssid", "").strip(),
                "password": form.get("wifi_password", "").strip(),
                "method": form.get("wifi_method", "dhcp").strip(),
                "address": form.get("wifi_address", "").strip(),
                "netmask": form.get("wifi_netmask", "").strip(),
                "gateway": form.get("wifi_gateway", "").strip(),
                "dns": wifi_dns,
            },
        },
    }


def _list_timezones() -> list[str]:
    """Получить список доступных часовых поясов из системы."""
    import subprocess
    try:
        result = subprocess.run(
            ["timedatectl", "list-timezones"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            zones = [z.strip() for z in result.stdout.splitlines() if z.strip()]
            if zones:
                return zones
    except Exception:
        pass
    # Fallback — базовый список частых поясов
    return [
        "Europe/Moscow",
        "Europe/Kaliningrad",
        "Europe/Samara",
        "Europe/Yekaterinburg",
        "Europe/Omsk",
        "Europe/Krasnoyarsk",
        "Asia/Novosibirsk",
        "Asia/Irkutsk",
        "Asia/Yakutsk",
        "Asia/Vladivostok",
        "Asia/Magadan",
        "Asia/Kamchatka",
        "UTC",
    ]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Веб-интерфейс СКУД")
    parser.add_argument("--config", help="Путь к config.yml")
    parser.add_argument("--host", default="0.0.0.0", help="Хост для прослушивания")
    parser.add_argument("--port", type=int, default=8080, help="Порт")
    parser.add_argument("--debug", action="store_true", help="Режим отладки Flask")
    parser.add_argument("--cert", help="Путь к SSL-сертификату (PEM)")
    parser.add_argument("--key", help="Путь к SSL-ключу (PEM)")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO)
    app = create_app(args.config)

    ssl_context = None
    if args.cert and args.key:
        ssl_context = (args.cert, args.key)
    elif args.cert is None and args.key is None:
        # Авто: ищем сертификат в стандартном месте
        import os
        # base_dir — каталог, где лежит config.yml (обычно app/)
        config_path = args.config or os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "config.yml",
        )
        base_dir = os.path.dirname(os.path.abspath(config_path))
        cert = os.path.join(base_dir, "infrastructure", "certs", "web", "cert.pem")
        key = os.path.join(base_dir, "infrastructure", "certs", "web", "key.pem")
        if os.path.exists(cert) and os.path.exists(key):
            ssl_context = (cert, key)

    app.run(host=args.host, port=args.port, debug=args.debug, ssl_context=ssl_context)


if __name__ == "__main__":
    main()
