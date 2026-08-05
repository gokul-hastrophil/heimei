from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from heimei.doctor.base import Category, Finding, HealthCheck, Severity
from heimei.doctor.registry import CheckRegistry

if TYPE_CHECKING:
    from heimei.inventory import InventoryService


class DoctorService:
    """The rule engine. Resolves InventoryService exactly once (at
    construction) and reuses it for every run — checks never resolve
    anything themselves. No business logic beyond running checks and
    collecting Findings: it does not interpret, filter, or aggregate
    results. See ADR-0014.
    """

    def __init__(self, inventory: InventoryService) -> None:
        self._inventory = inventory
        self._registry = CheckRegistry()

    def register(self, check: HealthCheck) -> None:
        self._registry.register(check)

    def run(
        self, *, category: Category | None = None, check: str | None = None
    ) -> tuple[Finding, ...]:
        """Run registered checks and return their Findings.

        ``check`` (a check name) takes precedence over ``category`` if
        both are given. With neither, every registered check runs.
        """
        checks: tuple[HealthCheck, ...]
        if check is not None:
            checks = (self._registry.get(check),)
        elif category is not None:
            checks = self._registry.by_category(category)
        else:
            checks = self._registry.all()

        findings: list[Finding] = []
        for one_check in checks:
            findings.extend(self._run_one(one_check))
        return tuple(findings)

    def _run_one(self, check: HealthCheck) -> tuple[Finding, ...]:
        """A check that raises does not abort the run — it becomes a
        CRITICAL Finding naming the check, so one broken check can't
        silence every other independent check. See ADR-0014, section 3.
        """
        try:
            return check.run(self._inventory)
        except Exception as exc:
            return (
                Finding(
                    check=check.name,
                    category=check.category,
                    severity=Severity.CRITICAL,
                    message=f"{check.name} check failed to run: {exc}",
                    evaluated_at=datetime.now(UTC),
                ),
            )
