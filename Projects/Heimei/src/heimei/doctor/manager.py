from __future__ import annotations

from typing import TYPE_CHECKING

from heimei.doctor.checks import (
    CpuCheck,
    DockerCheck,
    GpuCheck,
    MemoryCheck,
    NetworkCheck,
    StorageCheck,
)
from heimei.doctor.service import DoctorService

if TYPE_CHECKING:
    from heimei.core.context import RuntimeContext
    from heimei.core.health import HealthStatus


class DoctorManager:
    """Implements the Manager lifecycle (ADR-0011) for Heimei's Doctor.

    Resolves InventoryService exactly once, during `initialize()`, and
    hands it to `DoctorService` at construction — checks never resolve
    anything themselves. Registers every built-in check explicitly; no
    auto-discovery, no plugins. See ADR-0014.

    `heimei.core.health`/`heimei.core.context`/`heimei.inventory`/
    `heimei.logging` are imported locally (inside methods, not at module
    level) rather than at the top of this file. This is not a style
    preference: `heimei.core.__init__` eagerly imports `Application`,
    which imports every manager — so a module-level import here would
    make loading `heimei.doctor` (e.g. via `heimei.cli.doctor`, before
    `heimei.core` gets a clean first entry) risk a genuine circular
    import. Deferring these imports to call time is always safe, since
    nothing can call a Manager's lifecycle methods before the whole
    module graph has already finished loading.
    """

    name = "doctor"
    dependencies: tuple[str, ...] = ("logging", "inventory")

    def __init__(self) -> None:
        self.service: DoctorService | None = None
        self._initialized = False
        self._shut_down = False

    def initialize(self, context: RuntimeContext) -> None:
        from heimei.inventory import InventoryService
        from heimei.logging import LoggingService

        logger = context.services.get(LoggingService)
        logger.info("Doctor manager initialized", subsystem="doctor")

        inventory = context.services.get(InventoryService)
        service = DoctorService(inventory)
        for check in (
            CpuCheck(),
            MemoryCheck(),
            StorageCheck(),
            NetworkCheck(),
            GpuCheck(),
            DockerCheck(),
        ):
            service.register(check)

        context.services.register(DoctorService, service)
        self.service = service
        self._initialized = True

    def startup(self) -> None:
        pass

    def health(self) -> HealthStatus:
        from heimei.core.health import HealthState, HealthStatus

        if not self._initialized or self._shut_down or self.service is None:
            return HealthStatus(state=HealthState.UNHEALTHY, detail="doctor is not active")
        return HealthStatus(state=HealthState.HEALTHY)

    def shutdown(self) -> None:
        self._shut_down = True
