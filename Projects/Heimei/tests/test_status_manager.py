import pytest
from loguru import logger

from heimei.config import ConfigurationService
from heimei.core.container import ServiceContainer
from heimei.core.context import RuntimeContext
from heimei.core.errors import ServiceNotRegisteredError
from heimei.core.health import HealthState
from heimei.core.runtime import Runtime
from heimei.doctor.manager import DoctorManager
from heimei.inventory.manager import InventoryManager
from heimei.logging.manager import LoggingManager
from heimei.status.manager import StatusManager
from heimei.status.service import StatusService


@pytest.fixture(autouse=True)
def clean_loguru():
    logger.remove()
    yield
    logger.remove()


@pytest.fixture
def log_dir(tmp_path):
    return tmp_path / "logs"


@pytest.fixture
def container(manifest_dir, log_dir, write_logging_manifest):
    write_logging_manifest(
        manifest_dir,
        {"level": "INFO", "console": True, "file": True, "directory": str(log_dir)},
    )
    service_container = ServiceContainer()
    service_container.register(
        ConfigurationService, ConfigurationService(manifest_dir=manifest_dir)
    )
    return service_container


@pytest.fixture
def bootstrapped(container):
    """Status needs Logging, Inventory, and Doctor already initialized,
    exactly as the Runtime would guarantee via dependency ordering.
    """
    context = RuntimeContext(services=container)
    LoggingManager().initialize(context)
    InventoryManager().initialize(context)
    DoctorManager().initialize(context)
    return context


def test_manager_identity():
    manager = StatusManager(Runtime(ServiceContainer()))

    assert manager.name == "status"
    assert manager.dependencies == ("logging", "inventory", "doctor")


def test_health_before_initialize_is_unhealthy():
    manager = StatusManager(Runtime(ServiceContainer()))

    assert manager.health().state is HealthState.UNHEALTHY


def test_initialize_registers_the_service_into_the_container(bootstrapped):
    manager = StatusManager(Runtime(bootstrapped.services))

    manager.initialize(bootstrapped)

    assert bootstrapped.services.has(StatusService) is True
    assert bootstrapped.services.get(StatusService) is manager.service


def test_initialize_logs_via_logging_service(capsys, bootstrapped):
    manager = StatusManager(Runtime(bootstrapped.services))

    manager.initialize(bootstrapped)

    captured = capsys.readouterr()
    assert "Status manager initialized" in captured.err
    assert captured.out == ""


def test_initialize_requires_doctor_service_already_present(container):
    context = RuntimeContext(services=container)
    LoggingManager().initialize(context)
    InventoryManager().initialize(context)
    # DoctorManager deliberately not initialized here.
    manager = StatusManager(Runtime(container))

    with pytest.raises(ServiceNotRegisteredError):
        manager.initialize(context)


def test_initialize_requires_inventory_service_already_present(container):
    context = RuntimeContext(services=container)
    LoggingManager().initialize(context)
    # InventoryManager deliberately not initialized here.
    manager = StatusManager(Runtime(container))

    with pytest.raises(ServiceNotRegisteredError):
        manager.initialize(context)


def test_health_after_initialize_is_healthy(bootstrapped):
    manager = StatusManager(Runtime(bootstrapped.services))
    manager.initialize(bootstrapped)

    assert manager.health().state is HealthState.HEALTHY


def test_startup_is_a_safe_no_op(bootstrapped):
    manager = StatusManager(Runtime(bootstrapped.services))
    manager.initialize(bootstrapped)

    manager.startup()

    assert manager.health().state is HealthState.HEALTHY


def test_shutdown_marks_manager_unhealthy(bootstrapped):
    manager = StatusManager(Runtime(bootstrapped.services))
    manager.initialize(bootstrapped)

    manager.shutdown()

    assert manager.health().state is HealthState.UNHEALTHY


def test_service_produces_a_real_snapshot_using_the_bootstrapped_services(bootstrapped):
    runtime = Runtime(bootstrapped.services)
    manager = StatusManager(runtime)
    manager.initialize(bootstrapped)

    snapshot = manager.service.snapshot()

    # This throwaway Runtime never had any manager registered on it —
    # only Runtime.managers is exercised here, not the full dependency
    # graph; that's covered in test_status_runtime_integration.py.
    assert snapshot.runtime.manager_count == 0
    assert snapshot.machine.hostname
    assert snapshot.cpu.logical_cores >= 1
