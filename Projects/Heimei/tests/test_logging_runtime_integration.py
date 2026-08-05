import json

import pytest
from loguru import logger

from heimei.config import ConfigurationService
from heimei.core.container import ServiceContainer
from heimei.core.health import HealthState, HealthStatus
from heimei.core.runtime import ManagerState, Runtime
from heimei.logging.manager import LoggingManager
from heimei.logging.service import LoggingService


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


def test_logging_manager_registers_and_starts_via_runtime(container):
    runtime = Runtime(container)
    manager = LoggingManager()
    runtime.register(manager)

    runtime.startup()

    (record,) = runtime.managers
    assert record.name == "logging"
    assert record.state is ManagerState.STARTED
    assert record.health.state.name == "HEALTHY"


def test_other_code_resolves_logging_service_through_the_container(container):
    runtime = Runtime(container)
    runtime.register(LoggingManager())
    runtime.startup()

    service = container.get(LoggingService)
    service.info("resolved and used like any other manager would")

    runtime.shutdown()


def test_end_to_end_log_call_reaches_the_file_sink_with_structured_fields(container, log_dir):
    runtime = Runtime(container)
    runtime.register(LoggingManager())
    runtime.startup()

    container.get(LoggingService).info(
        "Runtime started", subsystem="runtime", manager="logging"
    )

    runtime.shutdown()

    (line,) = (log_dir / "heimei.log").read_text().strip().splitlines()
    record = json.loads(line)["record"]
    assert record["message"] == "Runtime started"
    assert record["extra"] == {"subsystem": "runtime", "manager": "logging"}


def test_logging_manager_coexists_with_other_managers_in_dependency_order(container, log_dir):
    runtime = Runtime(container)
    calls = []

    class OtherManager:
        name = "other"
        dependencies = ("logging",)

        def initialize(self, context):
            calls.append("other-initialize")
            self.logger = context.services.get(LoggingService)

        def startup(self):
            calls.append("other-startup")
            self.logger.info("other manager is up")

        def health(self):
            return HealthStatus(state=HealthState.HEALTHY)

        def shutdown(self):
            calls.append("other-shutdown")

    runtime.register(LoggingManager())
    runtime.register(OtherManager())

    runtime.startup()
    runtime.shutdown()

    assert calls == ["other-initialize", "other-startup", "other-shutdown"]
    assert "other manager is up" in (log_dir / "heimei.log").read_text()


def test_runtime_shutdown_leaves_logging_unhealthy(container):
    runtime = Runtime(container)
    manager = LoggingManager()
    runtime.register(manager)
    runtime.startup()

    runtime.shutdown()

    assert manager.health().state.name == "UNHEALTHY"
