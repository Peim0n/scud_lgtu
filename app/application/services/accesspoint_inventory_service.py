"""
Сервис инвентаризации контроллера на бэкенде (ресурс ``accesspoint``, §6.5 ТЗ).

Отправляет MAC-адрес, локальный IP и идентификатор ЦП контроллера на
бэкенд, чтобы тот мог связать физический контроллер с записью точки
доступа (турникета), созданной администратором в БД (§5.4.1: "Для
добавления микроконтроллера турникета в систему необходимо добавить
соответствующую запись в БД").

Классы
------
- AccesspointInventoryService: разовая/периодическая отправка инвентаризации.
"""
import logging
import socket
import uuid

logger = logging.getLogger(__name__)


def get_mac_address(interface: str | None = None) -> str:
    """
    Получить MAC-адрес сетевого интерфейса в формате ``aa:bb:cc:dd:ee:ff``.

    Если ``interface`` указан и есть ``/sys/class/net/<interface>/address`` —
    читаем оттуда (точный адрес нужного интерфейса на Linux). Иначе — общий
    фолбэк через ``uuid.getnode()`` (может не совпадать с физическим
    интерфейсом связи с бэкендом на многосетевых устройствах).
    """
    if interface:
        try:
            with open(f"/sys/class/net/{interface}/address", "r", encoding="utf-8") as f:
                return f.read().strip().lower()
        except OSError:
            logger.warning("get_mac_address: не удалось прочитать MAC интерфейса %s, используем фолбэк", interface)

    mac_int = uuid.getnode()
    mac_hex = f"{mac_int:012x}"
    return ":".join(mac_hex[i:i + 2] for i in range(0, 12, 2))


def get_local_ip(probe_host: str = "8.8.8.8", probe_port: int = 80) -> str:
    """
    Получить локальный IPv4-адрес исходящего интерфейса.

    Не делает реального сетевого обращения (UDP-сокет не отправляет
    пакетов при ``connect()``), только определяет, какой локальный адрес ОС
    выбрала бы для маршрута к ``probe_host``.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect((probe_host, probe_port))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


def get_cpu_id() -> str:
    """
    Получить серийный номер/идентификатор ЦП контроллера в hex.

    Пробует источники, характерные для одноплатных компьютеров на ARM
    (Orange Pi/Raspberry Pi и аналоги): device-tree serial-number, затем
    ``/proc/cpuinfo`` поле ``Serial``. Если ничего не найдено — детерминированный
    фолбэк на основе MAC-адреса (не идеально, но не даёт пустого значения).
    """
    dt_path = "/sys/firmware/devicetree/base/serial-number"
    try:
        with open(dt_path, "rb") as f:
            raw = f.read().rstrip(b"\x00").decode("ascii", errors="ignore").strip()
            if raw:
                return raw.lower()
    except OSError:
        pass

    try:
        with open("/proc/cpuinfo", "r", encoding="utf-8") as f:
            for line in f:
                if line.lower().startswith("serial"):
                    return line.split(":", 1)[1].strip().lower()
    except OSError:
        pass

    logger.warning("get_cpu_id: серийный номер ЦП не найден, используем MAC как фолбэк")
    return f"{uuid.getnode():012x}"


class AccesspointInventoryService:
    """Отправляет инвентаризационные данные контроллера на бэкенд."""

    def __init__(self, backend, interface: str | None = None, sync_interval_s: float = 86400.0):
        self._backend = backend
        self._interface = interface
        self._sync_interval = sync_interval_s
        self._last_sync = 0.0
        self._sent_once = False

    def tick(self, now: float) -> None:
        # Отправляем один раз сразу и затем повторяем на случай смены IP/сети.
        if not self._sent_once or (now - self._last_sync) >= self._sync_interval:
            self._sync()
            self._last_sync = now

    def _sync(self) -> None:
        if not self._backend.is_online():
            return
        mac = get_mac_address(self._interface)
        ip = get_local_ip()
        cpuid = get_cpu_id()
        try:
            self._backend.patch_accesspoint(mac=mac, ip=ip, cpuid=cpuid)
            self._sent_once = True
            logger.info("AccesspointInventoryService: инвентаризация отправлена (mac=%s ip=%s)", mac, ip)
        except Exception:
            logger.exception("AccesspointInventoryService: не удалось отправить инвентаризацию")
