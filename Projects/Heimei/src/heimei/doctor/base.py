from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Protocol

from pydantic import BaseModel

if TYPE_CHECKING:
    # Type-hint only. Deferred so heimei.doctor never triggers
    # heimei.inventory (and transitively heimei.core) at module-import
    # time — that path is exactly what caused a real circular import
    # once heimei.cli.doctor could be reached before heimei.core's own
    # first, clean entry. See ADR-0014's implementation notes.
    from heimei.inventory import InventoryService


class Severity(Enum):
    """A Finding's severity. Deliberately distinct from
    ``heimei.core.health.HealthState`` — a Manager's own operational
    health and a judgment about the machine are different questions;
    see ADR-0014, section 1.
    """

    OK = "ok"
    WARNING = "warning"
    CRITICAL = "critical"


class Category(Enum):
    """Which area of machine state a Finding is about."""

    HARDWARE = "hardware"
    SOFTWARE = "software"
    GPU = "gpu"
    DOCKER = "docker"
    STORAGE = "storage"
    NETWORK = "network"
    CONFIGURATION = "configuration"
    PERFORMANCE = "performance"


class Finding(BaseModel):
    """One result produced by a single HealthCheck. See ADR-0014."""

    check: str
    category: Category
    severity: Severity
    message: str
    detail: dict[str, object] | None = None
    evaluated_at: datetime


class HealthCheck(Protocol):
    """The contract every check implements — see ADR-0014.

    ``run`` receives ``InventoryService`` directly, never the
    ``ServiceContainer``: a check should not need to know how services
    are resolved, only which Inventory data it needs. This keeps checks
    independent of the platform (Runtime/Container) they happen to run
    under.
    """

    name: str
    category: Category

    def run(self, inventory: InventoryService) -> tuple[Finding, ...]: ...


class DoctorError(Exception):
    """Base class for all Doctor errors."""


class DuplicateCheckError(DoctorError):
    def __init__(self, name: str):
        self.name = name
        super().__init__(f"A check named {name!r} is already registered")


class CheckNotFoundError(DoctorError):
    def __init__(self, name: str):
        self.name = name
        super().__init__(f"No check named {name!r} is registered")
