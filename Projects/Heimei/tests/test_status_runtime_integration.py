import pytest
from loguru import logger

from heimei.config import ConfigurationService
from heimei.core.container import ServiceContainer
from heimei.core.errors import UnknownDependencyError
from heimei.core.runtime import ManagerState, Runtime
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


def test_status_manager_registers_and_starts_via_runtime(container):
    runtime = Runtime(container)
    runtime.register(LoggingManager())
    runtime.register(InventoryManager())
    runtime.register(DoctorManager())
    runtime.register(StatusManager(runtime))

    runtime.startup()

    records = {record.name: record for record in runtime.managers}
    assert records["status"].state is ManagerState.STARTED
    assert records["status"].health.state.name == "HEALTHY"

    runtime.shutdown()


def test_dependency_ordering_starts_logging_inventory_and_doctor_before_status(container):
    runtime = Runtime(container)
    # Registered out of dependency order deliberately.
    runtime.register(StatusManager(runtime))
    runtime.register(DoctorManager())
    runtime.register(InventoryManager())
    runtime.register(LoggingManager())

    runtime.startup()

    order = {record.name: record.order for record in runtime.managers}
    assert order["logging"] < order["status"]
    assert order["inventory"] < order["status"]
    assert order["doctor"] < order["status"]

    runtime.shutdown()


def test_status_service_resolvable_through_the_container_after_startup(container):
    runtime = Runtime(container)
    runtime.register(LoggingManager())
    runtime.register(InventoryManager())
    runtime.register(DoctorManager())
    runtime.register(StatusManager(runtime))
    runtime.startup()

    status_service = container.get(StatusService)
    snapshot = status_service.snapshot()

    assert snapshot.runtime.manager_count == 4
    assert snapshot.runtime.all_managers_started is True

    runtime.shutdown()


def test_end_to_end_snapshot_against_real_services_produces_no_crashes(container):
    """Status's aggregation runs against the real machine (via the real
    InventoryService and DoctorService, not fakes) — it must not raise,
    and every field must be populated.
    """
    runtime = Runtime(container)
    runtime.register(LoggingManager())
    runtime.register(InventoryManager())
    runtime.register(DoctorManager())
    runtime.register(StatusManager(runtime))
    runtime.startup()

    status_service = container.get(StatusService)
    snapshot = status_service.snapshot()

    assert snapshot.machine.hostname
    assert snapshot.cpu.logical_cores >= 1
    total_findings = snapshot.findings.ok + snapshot.findings.warning + snapshot.findings.critical
    assert total_findings >= 6  # at least one per built-in Doctor check

    runtime.shutdown()


def test_unknown_dependency_raises_if_doctor_never_registered(container):
    runtime = Runtime(container)
    runtime.register(LoggingManager())
    runtime.register(InventoryManager())
    runtime.register(StatusManager(runtime))
    # DoctorManager deliberately never registered.

    with pytest.raises(UnknownDependencyError):
        runtime.startup()
