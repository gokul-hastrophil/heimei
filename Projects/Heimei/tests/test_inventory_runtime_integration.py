import pytest
from loguru import logger

from heimei.config import ConfigurationService
from heimei.core.container import ServiceContainer
from heimei.core.runtime import ManagerState, Runtime
from heimei.inventory.manager import InventoryManager
from heimei.inventory.service import InventoryService
from heimei.logging.manager import LoggingManager


@pytest.fixture(autouse=True)
def clean_loguru():
    logger.remove()
    yield
    logger.remove()


@pytest.fixture
def container(manifest_dir, tmp_path, write_logging_manifest):
    write_logging_manifest(
        manifest_dir,
        {"level": "INFO", "console": True, "file": True, "directory": str(tmp_path / "logs")},
    )
    service_container = ServiceContainer()
    service_container.register(
        ConfigurationService, ConfigurationService(manifest_dir=manifest_dir)
    )
    return service_container


def test_inventory_manager_registers_and_starts_via_runtime(container):
    runtime = Runtime(container)
    runtime.register(LoggingManager())
    runtime.register(InventoryManager())

    runtime.startup()

    records = {record.name: record for record in runtime.managers}
    assert records["inventory"].state is ManagerState.STARTED
    assert records["inventory"].health.state.name == "HEALTHY"


def test_dependency_ordering_initializes_logging_before_inventory(container):
    runtime = Runtime(container)
    # Register in reverse order deliberately — ordering must come from
    # the declared dependency, not registration order.
    runtime.register(InventoryManager())
    runtime.register(LoggingManager())

    runtime.startup()

    order = [record.name for record in sorted(runtime.managers, key=lambda r: r.order)]
    assert order == ["logging", "inventory"]


def test_inventory_service_resolvable_through_the_container_after_startup(container):
    runtime = Runtime(container)
    runtime.register(LoggingManager())
    runtime.register(InventoryManager())
    runtime.startup()

    inventory = container.get(InventoryService)

    assert inventory.machine().hostname
    runtime.shutdown()


def test_inventory_never_needs_to_resolve_logging_service_beyond_its_own_initialize(container):
    """Regression guard for directionality: InventoryService itself
    (as opposed to InventoryManager) must not reach for LoggingService
    or any other manager — it only reports facts to its callers.
    """
    runtime = Runtime(container)
    runtime.register(LoggingManager())
    runtime.register(InventoryManager())
    runtime.startup()

    inventory = container.get(InventoryService)
    import inspect

    source = inspect.getsource(type(inventory))
    assert "LoggingService" not in source
    assert "services.get" not in source

    runtime.shutdown()


def test_unknown_dependency_raises_if_logging_never_registered(container):
    from heimei.core.errors import UnknownDependencyError

    runtime = Runtime(container)
    runtime.register(InventoryManager())

    with pytest.raises(UnknownDependencyError):
        runtime.startup()
