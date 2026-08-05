from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from heimei.doctor.base import Category, Finding, Severity

if TYPE_CHECKING:
    from heimei.inventory import InventoryService


class MemoryCheck:
    name = "Memory"
    category = Category.PERFORMANCE

    WARNING_PERCENT = 75.0
    CRITICAL_PERCENT = 90.0

    def run(self, inventory: InventoryService) -> tuple[Finding, ...]:
        memory = inventory.memory(refresh=True)
        now = datetime.now(UTC)

        if memory.percent >= self.CRITICAL_PERCENT:
            severity = Severity.CRITICAL
            message = f"Memory usage critically high ({memory.percent:.1f}%)"
        elif memory.percent >= self.WARNING_PERCENT:
            severity = Severity.WARNING
            message = f"Memory usage high ({memory.percent:.1f}%)"
        else:
            severity = Severity.OK
            message = f"Memory usage normal ({memory.percent:.1f}%)"

        return (
            Finding(
                check=self.name,
                category=self.category,
                severity=severity,
                message=message,
                evaluated_at=now,
                detail={"percent": memory.percent},
            ),
        )
