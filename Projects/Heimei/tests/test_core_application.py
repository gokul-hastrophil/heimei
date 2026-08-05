import pytest
from loguru import logger

from heimei.config import ConfigurationService, reset_configuration_service
from heimei.core.application import Application
from heimei.core.errors import RuntimeStateError
from heimei.core.runtime import ManagerState
from heimei.doctor import DoctorService
from heimei.inventory import InventoryService
from heimei.logging import LoggingService


@pytest.fixture(autouse=True)
def clean_loguru():
    logger.remove()
    yield
    logger.remove()


@pytest.fixture(autouse=True)
def isolated_home(monkeypatch, tmp_path, write_logging_manifest):
    monkeypatch.setenv("HEIMEI_HOME", str(tmp_path))
    write_logging_manifest(
        tmp_path / "System" / "manifest",
        {"level": "INFO", "console": True, "file": True, "directory": str(tmp_path / "logs")},
    )
    reset_configuration_service()
    yield
    reset_configuration_service()


def test_application_registers_configuration_into_its_container():
    app = Application()

    assert app.services.has(ConfigurationService) is True
    assert isinstance(app.services.get(ConfigurationService), ConfigurationService)


def test_application_registers_logging_inventory_and_doctor_managers_with_the_runtime():
    app = Application()

    names = {record.name for record in app.runtime.managers}
    assert names == {"logging", "inventory", "doctor"}


def test_application_start_and_stop_succeed_with_all_three_managers():
    app = Application()

    app.start()
    app.stop()

    names = {record.name for record in app.runtime.managers}
    assert names == {"logging", "inventory", "doctor"}


def test_application_start_orders_logging_and_inventory_before_doctor():
    app = Application()

    app.start()

    records = {record.name: record for record in app.runtime.managers}
    assert records["logging"].order < records["doctor"].order
    assert records["inventory"].order < records["doctor"].order
    for name in ("logging", "inventory", "doctor"):
        assert records[name].state is ManagerState.STARTED

    app.stop()


def test_application_start_makes_logging_service_resolvable():
    app = Application()

    app.start()

    assert app.services.has(LoggingService) is True
    app.stop()


def test_application_start_makes_inventory_service_resolvable():
    app = Application()

    app.start()

    assert app.services.has(InventoryService) is True
    assert app.services.get(InventoryService).machine().hostname
    app.stop()


def test_application_start_makes_doctor_service_resolvable():
    app = Application()

    app.start()

    assert app.services.has(DoctorService) is True
    findings = app.services.get(DoctorService).run()
    assert len(findings) > 0
    app.stop()


def test_application_stop_before_start_raises():
    app = Application()

    with pytest.raises(RuntimeStateError):
        app.stop()


def test_application_start_twice_raises():
    app = Application()
    app.start()

    with pytest.raises(RuntimeStateError):
        app.start()
