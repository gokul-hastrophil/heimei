from datetime import UTC, datetime

import pytest

from heimei.doctor.base import Category, Severity
from heimei.doctor.checks.gpu import GpuCheck
from heimei.inventory.collectors.gpu import GpuDevice, GpuSnapshot


class FakeInventory:
    def __init__(self, available, source, devices=()):
        self.refresh_requested = None
        self._snapshot = GpuSnapshot(
            collected_at=datetime.now(UTC),
            source=source,
            collector_version="1.0",
            available=available,
            devices=tuple(devices),
        )

    def gpu(self, *, refresh=False):
        self.refresh_requested = refresh
        return self._snapshot


def test_identity():
    check = GpuCheck()
    assert check.name == "GPU"
    assert check.category is Category.GPU


def test_requests_a_fresh_reading():
    check = GpuCheck()
    inventory = FakeInventory(available=False, source="none")

    check.run(inventory)

    assert inventory.refresh_requested is True


def test_no_gpu_is_ok():
    check = GpuCheck()

    (finding,) = check.run(FakeInventory(available=False, source="none"))

    assert finding.severity is Severity.OK
    assert "No GPU detected" in finding.message


@pytest.mark.parametrize("source", ["pynvml", "nvidia-smi"])
def test_driver_functioning_is_ok(source):
    check = GpuCheck()
    inventory = FakeInventory(
        available=True, source=source, devices=[GpuDevice(name="RTX 3050", memory_total_bytes=4096)]
    )

    (finding,) = check.run(inventory)

    assert finding.severity is Severity.OK
    assert source in finding.message


def test_lspci_nvidia_device_with_no_working_driver_is_critical():
    check = GpuCheck()
    inventory = FakeInventory(
        available=True, source="lspci", devices=[GpuDevice(name="NVIDIA GeForce RTX 3050")]
    )

    (finding,) = check.run(inventory)

    assert finding.severity is Severity.CRITICAL
    assert finding.message == "NVIDIA driver missing"


def test_lspci_non_nvidia_device_is_ok():
    check = GpuCheck()
    inventory = FakeInventory(
        available=True, source="lspci", devices=[GpuDevice(name="Intel UHD Graphics")]
    )

    (finding,) = check.run(inventory)

    assert finding.severity is Severity.OK
    assert "lspci" in finding.message
