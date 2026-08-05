import pytest
from loguru import logger

from heimei.config import ConfigurationService
from heimei.core.container import ServiceContainer
from heimei.core.context import RuntimeContext
from heimei.core.errors import ServiceNotRegisteredError
from heimei.core.health import HealthState
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


@pytest.fixture
def initialized_logging(container):
    """Inventory needs LoggingService already present, like it would be
    once the Runtime has initialized LoggingManager first.
    """
    logging_manager = LoggingManager()
    logging_manager.initialize(RuntimeContext(services=container))
    return logging_manager


def test_manager_identity():
    manager = InventoryManager()

    assert manager.name == "inventory"
    assert manager.dependencies == ("logging",)


def test_manager_exposes_an_inventory_service_from_construction():
    manager = InventoryManager()

    assert isinstance(manager.service, InventoryService)


def test_health_before_initialize_is_unhealthy():
    manager = InventoryManager()

    assert manager.health().state is HealthState.UNHEALTHY


def test_initialize_registers_the_service_into_the_container(container, initialized_logging):
    manager = InventoryManager()

    manager.initialize(RuntimeContext(services=container))

    assert container.has(InventoryService) is True
    assert container.get(InventoryService) is manager.service


def test_initialize_logs_via_logging_service_not_print(capsys, container, initialized_logging):
    manager = InventoryManager()

    manager.initialize(RuntimeContext(services=container))

    captured = capsys.readouterr()
    assert "Inventory manager initialized" in captured.err
    assert captured.out == ""  # never a bare print()


def test_initialize_requires_logging_service_already_present(container):
    manager = InventoryManager()

    with pytest.raises(ServiceNotRegisteredError):
        manager.initialize(RuntimeContext(services=container))


def test_health_after_initialize_is_healthy(container, initialized_logging):
    manager = InventoryManager()
    manager.initialize(RuntimeContext(services=container))

    assert manager.health().state is HealthState.HEALTHY


def test_startup_is_a_safe_no_op(container, initialized_logging):
    manager = InventoryManager()
    manager.initialize(RuntimeContext(services=container))

    manager.startup()  # must not raise

    assert manager.health().state is HealthState.HEALTHY


def test_shutdown_marks_manager_unhealthy(container, initialized_logging):
    manager = InventoryManager()
    manager.initialize(RuntimeContext(services=container))

    manager.shutdown()

    assert manager.health().state is HealthState.UNHEALTHY
