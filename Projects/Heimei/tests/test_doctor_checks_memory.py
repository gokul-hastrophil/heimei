from datetime import UTC, datetime

from heimei.doctor.base import Category, Severity
from heimei.doctor.checks.memory import MemoryCheck
from heimei.inventory.collectors.memory import MemorySnapshot


class FakeInventory:
    def __init__(self, percent):
        self.refresh_requested = None
        self._percent = percent

    def memory(self, *, refresh=False):
        self.refresh_requested = refresh
        return MemorySnapshot(
            collected_at=datetime.now(UTC),
            source="fake",
            collector_version="1.0",
            total_bytes=16_000_000_000,
            available_bytes=int(16_000_000_000 * (1 - self._percent / 100)),
            percent=self._percent,
        )


def test_identity():
    check = MemoryCheck()
    assert check.name == "Memory"
    assert check.category is Category.PERFORMANCE


def test_requests_a_fresh_reading():
    check = MemoryCheck()
    inventory = FakeInventory(percent=10.0)

    check.run(inventory)

    assert inventory.refresh_requested is True


def test_low_usage_is_ok():
    check = MemoryCheck()

    (finding,) = check.run(FakeInventory(percent=10.0))

    assert finding.severity is Severity.OK
    assert finding.category is Category.PERFORMANCE


def test_usage_at_warning_threshold_is_warning():
    check = MemoryCheck()

    (finding,) = check.run(FakeInventory(percent=80.0))

    assert finding.severity is Severity.WARNING
    assert "high" in finding.message.lower()


def test_usage_at_critical_threshold_is_critical():
    check = MemoryCheck()

    (finding,) = check.run(FakeInventory(percent=95.0))

    assert finding.severity is Severity.CRITICAL
    assert "critically high" in finding.message.lower()
