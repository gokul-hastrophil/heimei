from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from heimei.doctor.base import Category, Finding, Severity

if TYPE_CHECKING:
    from heimei.inventory import InventoryService


def _is_relevant_mount(path: str) -> bool:
    """Excludes mounts where "percent used" is structurally meaningless.

    Snap packages mount as fixed-size, read-only squashfs images under
    ``/snap/<name>/<revision>`` — they always report ~0% free by design,
    not because anything is wrong. `StorageMount` (Inventory, frozen)
    carries no filesystem-type/read-only flag to detect this more
    generally, so this is a targeted, path-based filter rather than a
    fstype check — see ADR-0014's implementation notes for why this
    couldn't be done more precisely without changing frozen Inventory.
    """
    return not path.startswith("/snap/")


class StorageCheck:
    name = "Storage"
    category = Category.STORAGE

    WARNING_FREE_PERCENT = 15.0
    CRITICAL_FREE_PERCENT = 5.0

    def run(self, inventory: InventoryService) -> tuple[Finding, ...]:
        storage = inventory.storage(refresh=True)
        now = datetime.now(UTC)

        mounts = [mount for mount in storage.mounts if _is_relevant_mount(mount.path)]
        if not mounts:
            return (
                Finding(
                    check=self.name,
                    category=self.category,
                    severity=Severity.OK,
                    message="No storage mounts detected",
                    evaluated_at=now,
                ),
            )

        findings = []
        for mount in mounts:
            free_percent = 100.0 - mount.percent
            detail = {"path": mount.path, "free_percent": free_percent}
            if free_percent < self.CRITICAL_FREE_PERCENT:
                severity = Severity.CRITICAL
                message = f"Disk usage critical on {mount.path} ({free_percent:.1f}% free)"
            elif free_percent < self.WARNING_FREE_PERCENT:
                severity = Severity.WARNING
                message = "Disk usage high"
            else:
                severity = Severity.OK
                message = f"{mount.path}: {free_percent:.1f}% free"
            findings.append(
                Finding(
                    check=self.name,
                    category=self.category,
                    severity=severity,
                    message=message,
                    evaluated_at=now,
                    detail=detail,
                )
            )
        return tuple(findings)
