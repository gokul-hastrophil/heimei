from __future__ import annotations

from typing import TYPE_CHECKING

from heimei.status.service import StatusService

if TYPE_CHECKING:
    from heimei.core import HealthStatus, Runtime, RuntimeContext


class StatusManager:
    """Implements the Manager lifecycle (ADR-0011) for Heimei's status view.

    Takes the Runtime it will report on as a constructor argument —
    Application hands it the same ``Runtime`` instance it already
    constructed, rather than Status resolving it from the
    ServiceContainer (which never holds a ``Runtime`` reference; adding
    one would be a change to how Core Runtime is wired, not just to
    Status). Resolves InventoryService and DoctorService from the
    container during ``initialize()``, same as DoctorManager resolves
    InventoryService. See ADR-0015.

    ``heimei.core``/``heimei.inventory``/``heimei.doctor``/``heimei.logging``
    are imported locally (inside methods, not at module level) for the
    same reason ``heimei.doctor.manager`` does this: ``heimei.core.__init__``
    eagerly imports ``Application``, which imports every manager — a
    module-level import here would risk the same circular import Doctor
    hit and fixed. Deferring to call time is always safe, since nothing
    calls a Manager's lifecycle methods before the whole module graph has
    already finished loading.
    """

    name = "status"
    dependencies: tuple[str, ...] = ("logging", "inventory", "doctor")

    def __init__(self, runtime: Runtime) -> None:
        self._runtime = runtime
        self.service: StatusService | None = None
        self._initialized = False
        self._shut_down = False

    def initialize(self, context: RuntimeContext) -> None:
        from heimei.doctor import DoctorService
        from heimei.inventory import InventoryService
        from heimei.logging import LoggingService

        logger = context.services.get(LoggingService)
        logger.info("Status manager initialized", subsystem="status")

        inventory = context.services.get(InventoryService)
        doctor = context.services.get(DoctorService)
        service = StatusService(self._runtime, inventory, doctor)

        context.services.register(StatusService, service)
        self.service = service
        self._initialized = True

    def startup(self) -> None:
        pass

    def health(self) -> HealthStatus:
        from heimei.core import HealthState, HealthStatus

        if not self._initialized or self._shut_down or self.service is None:
            return HealthStatus(state=HealthState.UNHEALTHY, detail="status is not active")
        return HealthStatus(state=HealthState.HEALTHY)

    def shutdown(self) -> None:
        self._shut_down = True
