from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from heimei.doctor.base import Category, Finding, Severity

if TYPE_CHECKING:
    from heimei.inventory import InventoryService


class NetworkCheck:
    name = "Network"
    category = Category.NETWORK

    def run(self, inventory: InventoryService) -> tuple[Finding, ...]:
        network = inventory.network(refresh=True)
        now = datetime.now(UTC)

        if not network.interfaces:
            return (
                Finding(
                    check=self.name,
                    category=self.category,
                    severity=Severity.WARNING,
                    message="No network interfaces detected",
                    evaluated_at=now,
                ),
            )

        with_addresses = [interface for interface in network.interfaces if interface.addresses]
        if not with_addresses:
            return (
                Finding(
                    check=self.name,
                    category=self.category,
                    severity=Severity.WARNING,
                    message="No network interface has an address",
                    evaluated_at=now,
                ),
            )

        return (
            Finding(
                check=self.name,
                category=self.category,
                severity=Severity.OK,
                message=f"{len(with_addresses)} network interface(s) with an address",
                evaluated_at=now,
                detail={"interfaces": [interface.name for interface in with_addresses]},
            ),
        )
