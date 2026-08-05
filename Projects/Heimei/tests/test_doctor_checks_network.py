from datetime import UTC, datetime

from heimei.doctor.base import Category, Severity
from heimei.doctor.checks.network import NetworkCheck
from heimei.inventory.collectors.network import NetworkInterface, NetworkSnapshot


class FakeInventory:
    def __init__(self, interfaces):
        self.refresh_requested = None
        self._interfaces = interfaces

    def network(self, *, refresh=False):
        self.refresh_requested = refresh
        return NetworkSnapshot(
            collected_at=datetime.now(UTC),
            source="fake",
            collector_version="1.0",
            interfaces=tuple(self._interfaces),
        )


def test_identity():
    check = NetworkCheck()
    assert check.name == "Network"
    assert check.category is Category.NETWORK


def test_requests_a_fresh_reading():
    check = NetworkCheck()
    inventory = FakeInventory([NetworkInterface(name="eth0", addresses=("10.0.0.5",))])

    check.run(inventory)

    assert inventory.refresh_requested is True


def test_interface_with_address_is_ok():
    check = NetworkCheck()

    (finding,) = check.run(FakeInventory([NetworkInterface(name="eth0", addresses=("10.0.0.5",))]))

    assert finding.severity is Severity.OK


def test_no_interfaces_is_warning():
    check = NetworkCheck()

    (finding,) = check.run(FakeInventory([]))

    assert finding.severity is Severity.WARNING
    assert "No network interfaces" in finding.message


def test_interfaces_with_no_addresses_is_warning():
    check = NetworkCheck()

    (finding,) = check.run(FakeInventory([NetworkInterface(name="lo", addresses=())]))

    assert finding.severity is Severity.WARNING
    assert "address" in finding.message.lower()
