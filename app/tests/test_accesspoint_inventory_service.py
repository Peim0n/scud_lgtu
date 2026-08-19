"""Тесты AccesspointInventoryService — инвентаризация контроллера (ресурс accesspoint, §6.5)."""
from unittest.mock import patch

from app.application.services.accesspoint_inventory_service import (
    AccesspointInventoryService,
)


class FakeBackend:
    def __init__(self, online=True):
        self._online = online
        self.patched = []

    def is_online(self):
        return self._online

    def patch_accesspoint(self, mac, ip, cpuid):
        self.patched.append({"mac": mac, "ip": ip, "cpuid": cpuid})


@patch("app.application.services.accesspoint_inventory_service.get_cpu_id", return_value="deadbeef")
@patch("app.application.services.accesspoint_inventory_service.get_local_ip", return_value="10.0.0.5")
@patch("app.application.services.accesspoint_inventory_service.get_mac_address", return_value="aa:bb:cc:dd:ee:ff")
def test_sends_inventory_on_first_tick(_mac, _ip, _cpuid):
    backend = FakeBackend()
    service = AccesspointInventoryService(backend, sync_interval_s=86400)

    service.tick(now=1000.0)

    assert backend.patched == [{"mac": "aa:bb:cc:dd:ee:ff", "ip": "10.0.0.5", "cpuid": "deadbeef"}]


@patch("app.application.services.accesspoint_inventory_service.get_cpu_id", return_value="deadbeef")
@patch("app.application.services.accesspoint_inventory_service.get_local_ip", return_value="10.0.0.5")
@patch("app.application.services.accesspoint_inventory_service.get_mac_address", return_value="aa:bb:cc:dd:ee:ff")
def test_does_not_resend_before_interval_elapsed(_mac, _ip, _cpuid):
    backend = FakeBackend()
    service = AccesspointInventoryService(backend, sync_interval_s=86400)

    service.tick(now=1000.0)
    service.tick(now=1000.0 + 10)

    assert len(backend.patched) == 1


def test_skips_when_backend_offline():
    backend = FakeBackend(online=False)
    service = AccesspointInventoryService(backend, sync_interval_s=86400)

    service.tick(now=1000.0)

    assert backend.patched == []
