from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from heimei.doctor.base import Category, Finding, Severity

if TYPE_CHECKING:
    from heimei.inventory import InventoryService


class DockerCheck:
    """Reports Docker status. Absence is not a failure — Doctor has no
    way (in this version) to know whether Docker is *expected* on this
    machine, so both "running" and "not detected" are OK. See ADR-0014,
    Future Work: Configuration-vs-Inventory reconciliation could turn
    this into a real pass/fail check later.
    """

    name = "Docker"
    category = Category.DOCKER

    def run(self, inventory: InventoryService) -> tuple[Finding, ...]:
        docker = inventory.docker(refresh=True)
        now = datetime.now(UTC)

        if docker.available:
            return (
                Finding(
                    check=self.name,
                    category=self.category,
                    severity=Severity.OK,
                    message=f"Docker running (v{docker.version})",
                    evaluated_at=now,
                    detail={"version": docker.version},
                ),
            )

        return (
            Finding(
                check=self.name,
                category=self.category,
                severity=Severity.OK,
                message="Docker not detected",
                evaluated_at=now,
            ),
        )
