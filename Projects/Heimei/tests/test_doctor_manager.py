import pytest
from loguru import logger

from heimei.config import ConfigurationService
from heimei.core.container import ServiceContainer
from heimei.core.context import RuntimeContext
from heimei.core.errors import ServiceNotRegisteredError
from heimei.core.health import HealthState
from heimei.doctor.manager import DoctorManager
from heimei.doctor.service import DoctorService
from heimei.inventory import InventoryService
from heimei.inventory.manager import InventoryManager
from heimei.logging.manager import LoggingManager


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
    """Doctor needs Logging and Inventory already initialized, exactly
    as the Runtime would guarantee via dependency ordering.
    """
    context = RuntimeContext(services=container)
    LoggingManager().initialize(context)
    InventoryManager().initialize(context)
    return context


def test_manager_identity():
    manager = DoctorManager()

    assert manager.name == "doctor"
    assert manager.dependencies == ("logging", "inventory")


def test_health_before_initialize_is_unhealthy():
    manager = DoctorManager()

    assert manager.health().state is HealthState.UNHEALTHY


def test_initialize_registers_the_service_into_the_container(bootstrapped):
    manager = DoctorManager()

    manager.initialize(bootstrapped)

    assert bootstrapped.services.has(DoctorService) is True
    assert bootstrapped.services.get(DoctorService) is manager.service


def test_initialize_logs_via_logging_service(capsys, bootstrapped):
    manager = DoctorManager()

    manager.initialize(bootstrapped)

    captured = capsys.readouterr()
    assert "Doctor manager initialized" in captured.err
    assert captured.out == ""


def test_initialize_registers_all_six_built_in_checks(bootstrapped):
    manager = DoctorManager()
    manager.initialize(bootstrapped)

    findings = manager.service.run()

    assert {finding.check for finding in findings} == {
        "CPU",
        "Memory",
        "Storage",
        "Network",
        "GPU",
        "Docker",
    }


def test_initialize_requires_inventory_service_already_present(container):
    manager = DoctorManager()
    context = RuntimeContext(services=container)
    LoggingManager().initialize(context)
    # InventoryManager deliberately not initialized here.

    with pytest.raises(ServiceNotRegisteredError):
        manager.initialize(context)


def test_health_after_initialize_is_healthy(bootstrapped):
    manager = DoctorManager()
    manager.initialize(bootstrapped)

    assert manager.health().state is HealthState.HEALTHY


def test_startup_is_a_safe_no_op(bootstrapped):
    manager = DoctorManager()
    manager.initialize(bootstrapped)

    manager.startup()

    assert manager.health().state is HealthState.HEALTHY


def test_shutdown_marks_manager_unhealthy(bootstrapped):
    manager = DoctorManager()
    manager.initialize(bootstrapped)

    manager.shutdown()

    assert manager.health().state is HealthState.UNHEALTHY


def test_service_uses_the_real_inventory_service_from_the_container(bootstrapped):
    manager = DoctorManager()
    manager.initialize(bootstrapped)

    real_inventory = bootstrapped.services.get(InventoryService)
    findings = manager.service.run(check="CPU")

    assert findings[0].check == "CPU"
    # sanity: the real InventoryService is usable and was actually consulted
    assert real_inventory.cpu().logical_cores >= 1
