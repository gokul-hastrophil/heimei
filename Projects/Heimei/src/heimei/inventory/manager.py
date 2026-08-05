from heimei.core.context import RuntimeContext
from heimei.core.health import HealthState, HealthStatus
from heimei.inventory.service import InventoryService
from heimei.logging import LoggingService


class InventoryManager:
    """Implements the Manager lifecycle (ADR-0011) for Heimei's inventory.

    Inventory is the single source of truth for live machine state. It
    depends on Logging for its own diagnostic output (never `print()`)
    but never depends on Status, Doctor, or any future consumer of its
    data — consumption flows one way, into Inventory's callers, never
    out of it. See ADR-0013.
    """

    name = "inventory"
    dependencies: tuple[str, ...] = ("logging",)

    def __init__(self) -> None:
        self.service = InventoryService()
        self._initialized = False
        self._shut_down = False

    def initialize(self, context: RuntimeContext) -> None:
        logger = context.services.get(LoggingService)
        logger.info("Inventory manager initialized", subsystem="inventory")

        context.services.register(InventoryService, self.service)
        self._initialized = True

    def startup(self) -> None:
        pass

    def health(self) -> HealthStatus:
        if not self._initialized or self._shut_down:
            return HealthStatus(state=HealthState.UNHEALTHY, detail="inventory is not active")
        return HealthStatus(state=HealthState.HEALTHY)

    def shutdown(self) -> None:
        self._shut_down = True
