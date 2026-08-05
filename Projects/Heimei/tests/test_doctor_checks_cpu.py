from datetime import UTC, datetime

from heimei.doctor.base import Category, Severity
from heimei.doctor.checks.cpu import CpuCheck
from heimei.inventory.collectors.cpu import CpuSnapshot


class FakeInventory:
    def __init__(self, logical_cores, physical_cores=None):
        self._snapshot = CpuSnapshot(
            collected_at=datetime.now(UTC),
            source="fake",
            collector_version="1.0",
            logical_cores=logical_cores,
            physical_cores=physical_cores,
            max_frequency_mhz=None,
        )

    def cpu(self):
        return self._snapshot


def test_identity():
    check = CpuCheck()
    assert check.name == "CPU"
    assert check.category is Category.HARDWARE


def test_healthy_core_count_is_ok():
    check = CpuCheck()

    (finding,) = check.run(FakeInventory(logical_cores=8, physical_cores=4))

    assert finding.severity is Severity.OK
    assert finding.category is Category.HARDWARE
    assert finding.check == "CPU"
    assert "8" in finding.message


def test_zero_cores_is_critical():
    check = CpuCheck()

    (finding,) = check.run(FakeInventory(logical_cores=0))

    assert finding.severity is Severity.CRITICAL
    assert "No CPU cores" in finding.message
