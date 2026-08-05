from heimei.config import ConfigurationService, get_configuration_service
from heimei.core.container import ServiceContainer
from heimei.core.runtime import Runtime
from heimei.doctor.manager import DoctorManager
from heimei.inventory.manager import InventoryManager
from heimei.logging.manager import LoggingManager
from heimei.status.manager import StatusManager


class Application:
    """Minimal application bootstrap: ServiceContainer, Configuration, Runtime.

    Configuration is registered directly into the ServiceContainer at
    construction time rather than run through the Manager lifecycle: it
    is stateless and lazy (ADR-0008), so it has no initialize/startup/
    health/shutdown behavior of its own. LoggingManager (ADR-0012),
    InventoryManager (ADR-0013), DoctorManager (ADR-0014), and
    StatusManager (ADR-0015) are registered with the Runtime, which
    derives their startup order from each manager's own declared
    dependencies — registration order here matches that derived order
    but does not dictate it. StatusManager is constructed with the
    Runtime instance itself (the only manager that needs it) rather than
    resolving it from the ServiceContainer, which never holds one — see
    ADR-0015, section 2.
    """

    def __init__(self) -> None:
        self.services = ServiceContainer()
        self.services.register(ConfigurationService, get_configuration_service())
        self.runtime = Runtime(self.services)
        self.runtime.register(LoggingManager())
        self.runtime.register(InventoryManager())
        self.runtime.register(DoctorManager())
        self.runtime.register(StatusManager(self.runtime))

    def start(self) -> None:
        self.runtime.startup()

    def stop(self) -> None:
        self.runtime.shutdown()
