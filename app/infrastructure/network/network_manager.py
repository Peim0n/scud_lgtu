"""Адаптер управления сетевым окружением контроллера.

Реализует чтение текущего состояния и применение настроек через:
- netplan + systemd-networkd (основной путь для Armbian/Debian);
- NetworkManager/nmcli (fallback, если установлен);
- hostnamectl, timedatectl — для hostname/timezone/NTP.

Если требуемый инструмент недоступен, метод возвращает ошибку, но не падает.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shlex
import subprocess
from typing import Any

logger = logging.getLogger(__name__)


def _run(
    cmd: list[str] | str,
    *,
    check: bool = False,
    timeout: float = 10.0,
) -> tuple[int, str, str]:
    """Запустить команду и вернуть (rc, stdout, stderr)."""
    if isinstance(cmd, str):
        cmd = shlex.split(cmd)
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except FileNotFoundError:
        return 127, "", f"команда не найдена: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"
    except Exception as exc:  # pragma: no cover
        logger.exception("Ошибка выполнения команды %s", cmd)
        return -1, "", str(exc)


def _ok(stdout: str) -> dict[str, Any]:
    return {"ok": True, "message": stdout or "ok"}


def _err(stderr: str) -> dict[str, Any]:
    return {"ok": False, "message": stderr or "unknown error"}


class NetworkManagerAdapter:
    """Управление сетевым окружением через системные утилиты."""

    def __init__(self) -> None:
        self._nmcli_available: bool | None = None
        self._netplan_available: bool | None = None

    def _has_nmcli(self) -> bool:
        if self._nmcli_available is None:
            rc, _, _ = _run(["which", "nmcli"])
            self._nmcli_available = rc == 0
        return self._nmcli_available

    def _has_netplan(self) -> bool:
        if self._netplan_available is None:
            rc, _, _ = _run(["which", "netplan"])
            self._netplan_available = rc == 0
        return self._netplan_available

    # -----------------------------------------------------------------------
    # Чтение текущего состояния
    # -----------------------------------------------------------------------

    def get_hostname(self) -> str:
        rc, out, _ = _run(["hostnamectl", "--static"])
        return out.strip() if rc == 0 else ""

    def get_timezone(self) -> str:
        rc, out, _ = _run(["timedatectl", "show", "--property=Timezone", "--value"])
        return out.strip() if rc == 0 else ""

    def get_ntp_status(self) -> dict[str, Any]:
        rc, out, err = _run(["timedatectl", "show-timesync"])
        if rc != 0:
            return {"ok": False, "message": err or "timedatectl failed"}
        status: dict[str, str] = {}
        for line in out.splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                status[k.strip()] = v.strip()
        return {"ok": True, "status": status}

    def list_interfaces(self) -> list[dict[str, Any]]:
        """Вернуть список сетевых интерфейсов с адресами."""
        rc, out, _ = _run(["ip", "-json", "addr", "show"])
        if rc == 0 and out:
            try:
                data = json.loads(out)
                return [
                    {
                        "name": iface.get("ifname"),
                        "state": iface.get("operstate"),
                        "addresses": [
                            addr.get("local")
                            for addr in iface.get("addr_info", [])
                            if addr.get("family") == "inet"
                        ],
                    }
                    for iface in data
                    if isinstance(iface, dict)
                ]
            except json.JSONDecodeError:
                pass

        # Fallback на не-json вывод
        rc, out, _ = _run(["ip", "addr", "show"])
        if rc != 0:
            return []
        interfaces = []
        current: dict[str, Any] | None = None
        for line in out.splitlines():
            m = re.match(r"^\d+:\s+([^:@]+).*state\s+(\w+)", line)
            if m:
                if current:
                    interfaces.append(current)
                current = {"name": m.group(1).strip(), "state": m.group(2), "addresses": []}
            elif current and "inet " in line:
                am = re.search(r"inet\s+([\d.]+)", line)
                if am:
                    current["addresses"].append(am.group(1))
        if current:
            interfaces.append(current)
        return interfaces

    def detect_ethernet_interface(self) -> str:
        """Определить имя ethernet-интерфейса (end0, eth0, enp0s3, ...)."""
        for iface in self.list_interfaces():
            name = iface.get("name", "")
            # Пропускаем lo и wlan
            if name == "lo" or name.startswith("wl"):
                continue
            if iface.get("state") in ("up", "unknown"):
                return name
        # Fallback: ищем через /sys/class/net
        try:
            for name in sorted(os.listdir("/sys/class/net")):
                if name == "lo" or name.startswith("wl"):
                    continue
                return name
        except OSError:
            pass
        return "eth0"

    def detect_wifi_interface(self) -> str:
        """Определить имя Wi-Fi-интерфейса (wlan0, wlp2s0, ...)."""
        for iface in self.list_interfaces():
            name = iface.get("name", "")
            if name.startswith("wl"):
                return name
        try:
            for name in sorted(os.listdir("/sys/class/net")):
                if name.startswith("wl"):
                    return name
        except OSError:
            pass
        return "wlan0"

    # -----------------------------------------------------------------------
    # Применение настроек
    # -----------------------------------------------------------------------

    def apply(self, config: dict[str, Any]) -> dict[str, Any]:
        """Применить сетевой конфиг. Возвращает результаты по секциям."""
        network_cfg = config.get("network", {})
        results: dict[str, Any] = {
            "hostname": self._apply_hostname(network_cfg.get("hostname", "")),
            "timezone": self._apply_timezone(network_cfg.get("timezone", "")),
            "ntp": self._apply_ntp(network_cfg.get("ntp_servers", [])),
            "ethernet": self._apply_ethernet(network_cfg.get("ethernet", {})),
            "wifi": self._apply_wifi(network_cfg.get("wifi", {})),
        }
        results["ok"] = all(r.get("ok", False) for r in results.values() if isinstance(r, dict))
        return results

    def _apply_hostname(self, hostname: str) -> dict[str, Any]:
        hostname = hostname.strip()
        if not hostname:
            return _ok("hostname не задан")
        rc, out, err = _run(["hostnamectl", "set-hostname", hostname])
        return _ok(out) if rc == 0 else _err(err)

    def _apply_timezone(self, timezone: str) -> dict[str, Any]:
        timezone = timezone.strip()
        if not timezone:
            return _ok("timezone не задана")
        rc, out, err = _run(["timedatectl", "set-timezone", timezone])
        return _ok(out) if rc == 0 else _err(err)

    def _apply_ntp(self, servers: list[str]) -> dict[str, Any]:
        if not servers:
            return _ok("ntp серверы не заданы")
        # Включаем NTP через timedatectl
        rc, out, err = _run(["timedatectl", "set-ntp", "true"])
        if rc != 0:
            return _err(err)
        # Пытаемся прописать серверы в timesyncd, если он используется
        try:
            lines = ["[Time]", f"NTP={', '.join(servers)}"]
            with open("/etc/systemd/timesyncd.conf", "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
            rc, out, err = _run(["systemctl", "restart", "systemd-timesyncd"])
            if rc != 0:
                return _err(err)
        except PermissionError:
            return _err("нет прав на запись /etc/systemd/timesyncd.conf")
        except OSError as exc:  # pragma: no cover
            return _err(str(exc))
        return _ok("ntp настроен")

    def _apply_ethernet(self, eth_cfg: dict[str, Any]) -> dict[str, Any]:
        if not eth_cfg:
            return _ok("ethernet не задан")
        if self._has_netplan():
            return self._apply_via_netplan("ethernet", eth_cfg)
        if self._has_nmcli():
            return self._apply_via_nmcli("ethernet", eth_cfg)
        return _err("не найден netplan или NetworkManager (nmcli)")

    def _apply_wifi(self, wifi_cfg: dict[str, Any]) -> dict[str, Any]:
        if not wifi_cfg:
            return _ok("wifi не задан")
        if not wifi_cfg.get("enabled"):
            return _ok("wifi выключен")
        if self._has_netplan():
            return self._apply_via_netplan("wifi", wifi_cfg)
        if self._has_nmcli():
            return self._apply_via_nmcli("wifi", wifi_cfg)
        return _err("не найден netplan или NetworkManager (nmcli)")

    # -----------------------------------------------------------------------
    # netplan + systemd-networkd
    # -----------------------------------------------------------------------

    _NETPLAN_DIR = "/etc/netplan"
    _NETPLAN_FILE = "/etc/netplan/10-scud-controller.yaml"

    def _apply_via_netplan(
        self, conn_type: str, cfg: dict[str, Any],
    ) -> dict[str, Any]:
        """Применить настройки через netplan."""
        interface = cfg.get("interface", "")
        if not interface:
            return _err("не указан interface")

        # Читаем существующий netplan-конфиг или начинаем с нуля
        netplan_cfg = self._read_netplan()

        # Гарантируем базовую структуру
        if "network" not in netplan_cfg:
            netplan_cfg["network"] = {}
        if "version" not in netplan_cfg["network"]:
            netplan_cfg["network"]["version"] = 2
        if "renderer" not in netplan_cfg["network"]:
            netplan_cfg["network"]["renderer"] = "networkd"

        if conn_type == "wifi":
            wifi_section = self._build_netplan_wifi(interface, cfg)
            netplan_cfg["network"]["wifis"] = {interface: wifi_section}
            # Удаляем ethernet-секцию для этого интерфейса, если была
            ethernets = netplan_cfg["network"].get("ethernets", {})
            ethernets.pop(interface, None)
            if ethernets:
                netplan_cfg["network"]["ethernets"] = ethernets
            else:
                netplan_cfg["network"].pop("ethernets", None)
        else:
            eth_section = self._build_netplan_ethernet(interface, cfg)
            if "ethernets" not in netplan_cfg["network"]:
                netplan_cfg["network"]["ethernets"] = {}
            netplan_cfg["network"]["ethernets"][interface] = eth_section

        # Записываем
        try:
            os.makedirs(self._NETPLAN_DIR, exist_ok=True)
            import yaml
            with open(self._NETPLAN_FILE, "w", encoding="utf-8") as f:
                yaml.safe_dump(netplan_cfg, f, default_flow_style=False, sort_keys=False)
            # Netplan требует права 600 — иначе ругается
            os.chmod(self._NETPLAN_FILE, 0o600)
        except PermissionError:
            return _err(f"нет прав на запись {self._NETPLAN_FILE}")
        except OSError as exc:
            return _err(str(exc))

        # Применяем
        rc, out, err = _run(["netplan", "apply"], timeout=30.0)
        if rc != 0:
            return _err(err or out)
        return _ok(f"{conn_type} применён через netplan")

    def _read_netplan(self) -> dict[str, Any]:
        """Прочитать наш netplan-конфиг, если есть."""
        if not os.path.exists(self._NETPLAN_FILE):
            return {}
        try:
            import yaml
            with open(self._NETPLAN_FILE, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            return data if data else {}
        except Exception:
            return {}

    def _build_netplan_ethernet(self, interface: str, cfg: dict[str, Any]) -> dict[str, Any]:
        """Построить секцию ethernets для netplan."""
        method = cfg.get("method", "dhcp")
        section: dict[str, Any] = {
            "match": {"name": interface},
        }
        if method == "static":
            address = cfg.get("address", "")
            netmask = cfg.get("netmask", "")
            gateway = cfg.get("gateway", "")
            dns = cfg.get("dns", [])
            if address:
                cidr = self._netmask_to_cidr(netmask) if netmask else 24
                section["addresses"] = [f"{address}/{cidr}"]
            if gateway:
                section["routes"] = [{"to": "default", "via": gateway}]
            if dns:
                section["nameservers"] = {"addresses": dns}
            section["dhcp4"] = False
            section["dhcp6"] = False
        else:
            section["dhcp4"] = True
            section["dhcp6"] = True
        return section

    def _build_netplan_wifi(self, interface: str, cfg: dict[str, Any]) -> dict[str, Any]:
        """Построить секцию wifis для netplan.

        Внимание: networkd backend не поддерживает match для wifis —
        имя интерфейса используется как ключ секции напрямую.
        """
        ssid = cfg.get("ssid", "")
        password = cfg.get("password", "")
        method = cfg.get("method", "dhcp")

        section: dict[str, Any] = {
            "access-points": {},
        }
        ap: dict[str, Any] = {}
        if password:
            ap["password"] = password
        section["access-points"][ssid] = ap

        if method == "static":
            address = cfg.get("address", "")
            netmask = cfg.get("netmask", "")
            gateway = cfg.get("gateway", "")
            dns = cfg.get("dns", [])
            if address:
                cidr = self._netmask_to_cidr(netmask) if netmask else 24
                section["addresses"] = [f"{address}/{cidr}"]
            if gateway:
                section["routes"] = [{"to": "default", "via": gateway}]
            if dns:
                section["nameservers"] = {"addresses": dns}
            section["dhcp4"] = False
            section["dhcp6"] = False
        else:
            section["dhcp4"] = True
            section["dhcp6"] = True
        return section

    # -----------------------------------------------------------------------
    # nmcli (fallback)
    # -----------------------------------------------------------------------

    def _apply_via_nmcli(
        self, conn_type: str, cfg: dict[str, Any],
    ) -> dict[str, Any]:
        """Применить настройки через nmcli."""
        interface = cfg.get("interface", "")
        method = cfg.get("method", "dhcp")
        if not interface:
            return _err("не указан interface")

        # Имя подключения в NM
        conn_name = f"{conn_type}-{interface}"

        # Удаляем старое подключение, если есть
        _run(["nmcli", "connection", "delete", conn_name], check=False)

        cmd: list[str]
        if conn_type == "wifi":
            ssid = cfg.get("ssid", "")
            password = cfg.get("password", "")
            if not ssid:
                return _err("не указан Wi-Fi SSID")
            cmd = [
                "nmcli", "connection", "add",
                "type", "wifi",
                "ifname", interface,
                "con-name", conn_name,
                "ssid", ssid,
            ]
            if password:
                cmd += ["wifi-sec.key-mgmt", "wpa-psk", "wifi-sec.psk", password]
        else:
            cmd = [
                "nmcli", "connection", "add",
                "type", "ethernet",
                "ifname", interface,
                "con-name", conn_name,
            ]

        rc, out, err = _run(cmd)
        if rc != 0:
            return _err(err or out)

        # IPv4 метод
        if method == "static":
            address = cfg.get("address", "")
            netmask = cfg.get("netmask", "")
            gateway = cfg.get("gateway", "")
            dns = cfg.get("dns", [])
            if not address or not netmask:
                return _err("для static нужен address и netmask")
            cidr = self._netmask_to_cidr(netmask)
            ipv4 = f"{address}/{cidr}"
            mod = ["nmcli", "connection", "modify", conn_name, "ipv4.method", "manual", "ipv4.addresses", ipv4]
            if gateway:
                mod += ["ipv4.gateway", gateway]
            if dns:
                mod += ["ipv4.dns", ",".join(dns)]
            rc, out, err = _run(mod)
            if rc != 0:
                return _err(err or out)
        else:
            rc, out, err = _run(["nmcli", "connection", "modify", conn_name, "ipv4.method", "auto"])
            if rc != 0:
                return _err(err or out)

        # Поднимаем соединение
        rc, out, err = _run(["nmcli", "connection", "up", conn_name])
        if rc != 0:
            return _err(err or out)

        return _ok(f"{conn_type} применено")

    @staticmethod
    def _netmask_to_cidr(netmask: str) -> int:
        """Преобразовать маску вида 255.255.255.0 в префикс."""
        try:
            octets = [int(o) for o in netmask.split(".")]
            bits = sum(bin(o).count("1") for o in octets)
            return bits
        except (ValueError, AttributeError):
            return 24


def get_manager() -> NetworkManagerAdapter:
    """Фабрика адаптера."""
    return NetworkManagerAdapter()
