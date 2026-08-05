import pytest
from loguru import logger

from heimei.config import ConfigurationService
from heimei.core.container import ServiceContainer
from heimei.core.errors import UnknownDependencyError
from heimei.core.runtime import ManagerState, Runtime
from heimei.doctor.base import Severity
from heimei.doctor.manager import DoctorManager
from heimei.doctor.service import DoctorService
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


def test_doctor_manager_registers_and_starts_via_runtime(container):
    runtime = Runtime(container)
    runtime.register(LoggingManager())
    runtime.register(InventoryManager())
    runtime.register(DoctorManager())

    runtime.startup()

    records = {record.name: record for record in runtime.managers}
    assert records["doctor"].state is ManagerState.STARTED
    assert records["doctor"].health.state.name == "HEALTHY"


def test_dependency_ordering_starts_logging_and_inventory_before_doctor(container):
    runtime = Runtime(container)
    # Registered out of dependency order deliberately.
    runtime.register(DoctorManager())
    runtime.register(InventoryManager())
    runtime.register(LoggingManager())

    runtime.startup()

    order = {record.name: record.order for record in runtime.managers}
    assert order["logging"] < order["doctor"]
    assert order["inventory"] < order["doctor"]


def test_doctor_service_resolvable_through_the_container_after_startup(container):
    runtime = Runtime(container)
    runtime.register(LoggingManager())
    runtime.register(InventoryManager())
    runtime.register(DoctorManager())
    runtime.startup()

    doctor = container.get(DoctorService)
    findings = doctor.run()

    assert len(findings) >= 6  # at least one per built-in check
    runtime.shutdown()


def test_end_to_end_run_against_real_inventory_produces_no_crashes(container):
    """Doctor's checks run against the real machine (via the real
    InventoryService, not a fake) — every check must produce at least
    one Finding and none may raise (failures become Findings instead).
    """
    runtime = Runtime(container)
    runtime.register(LoggingManager())
    runtime.register(InventoryManager())
    runtime.register(DoctorManager())
    runtime.startup()

    doctor = container.get(DoctorService)
    findings = doctor.run()

    by_check = {}
    for finding in findings:
        by_check.setdefault(finding.check, []).append(finding)
    assert set(by_check) == {"CPU", "Memory", "Storage", "Network", "GPU", "Docker"}
    for check_findings in by_check.values():
        assert all(f.severity in Severity for f in check_findings)

    runtime.shutdown()


def test_unknown_dependency_raises_if_inventory_never_registered(container):
    runtime = Runtime(container)
    runtime.register(LoggingManager())
    runtime.register(DoctorManager())
    # InventoryManager deliberately never registered.

    with pytest.raises(UnknownDependencyError):
        runtime.startup()
