from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from heimei.doctor.base import Category, Finding, Severity

if TYPE_CHECKING:
    from heimei.inventory import InventoryService


class CpuCheck:
    name = "CPU"
    category = Category.HARDWARE

    def run(self, inventory: InventoryService) -> tuple[Finding, ...]:
        cpu = inventory.cpu()
        now = datetime.now(UTC)

        if cpu.logical_cores < 1:
            return (
                Finding(
                    check=self.name,
                    category=self.category,
                    severity=Severity.CRITICAL,
                    message="No CPU cores detected",
                    evaluated_at=now,
                    detail={"logical_cores": cpu.logical_cores},
                ),
            )

        return (
            Finding(
                check=self.name,
                category=self.category,
                severity=Severity.OK,
                message=f"{cpu.logical_cores} logical cores detected",
                evaluated_at=now,
                detail={"logical_cores": cpu.logical_cores, "physical_cores": cpu.physical_cores},
            ),
        )
