from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from heimei.doctor.base import Category, Finding, Severity

if TYPE_CHECKING:
    from heimei.inventory import InventoryService


class GpuCheck:
    """Derives a real diagnostic from Inventory's own provenance
    (``GpuSnapshot.source``): if a GPU is visible on the PCI bus
    (``lspci``, which needs no vendor driver) but neither ``pynvml``
    nor ``nvidia-smi`` could reach it, and the device looks like an
    NVIDIA card, the NVIDIA driver is installed-but-not-functioning or
    missing entirely. No hardware is not a problem; hardware the driver
    stack can't see is.
    """

    name = "GPU"
    category = Category.GPU

    def run(self, inventory: InventoryService) -> tuple[Finding, ...]:
        gpu = inventory.gpu(refresh=True)
        now = datetime.now(UTC)

        if not gpu.available:
            return (
                Finding(
                    check=self.name,
                    category=self.category,
                    severity=Severity.OK,
                    message="No GPU detected",
                    evaluated_at=now,
                ),
            )

        if gpu.source in ("pynvml", "nvidia-smi"):
            return (
                Finding(
                    check=self.name,
                    category=self.category,
                    severity=Severity.OK,
                    message=f"GPU driver functioning ({gpu.source})",
                    evaluated_at=now,
                    detail={"devices": [device.name for device in gpu.devices]},
                ),
            )

        # source == "lspci": visible on the PCI bus, but the two more
        # capable layers (which would succeed if the driver stack were
        # healthy) both failed.
        nvidia_devices = [device for device in gpu.devices if "nvidia" in device.name.lower()]
        if nvidia_devices:
            return (
                Finding(
                    check=self.name,
                    category=self.category,
                    severity=Severity.CRITICAL,
                    message="NVIDIA driver missing",
                    evaluated_at=now,
                    detail={"devices": [device.name for device in nvidia_devices]},
                ),
            )

        return (
            Finding(
                check=self.name,
                category=self.category,
                severity=Severity.OK,
                message=f"GPU detected via lspci ({gpu.devices[0].name})",
                evaluated_at=now,
            ),
        )
