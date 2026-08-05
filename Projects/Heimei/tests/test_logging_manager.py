import sys

import pytest
from loguru import logger

from heimei.config import ConfigurationService
from heimei.core.container import ServiceContainer
from heimei.core.context import RuntimeContext
from heimei.core.health import HealthState
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


def _container_with_logging_manifest(manifest_dir, write_logging_manifest, data):
    write_logging_manifest(manifest_dir, data)
    container = ServiceContainer()
    container.register(ConfigurationService, ConfigurationService(manifest_dir=manifest_dir))
    return container


@pytest.fixture
def container(manifest_dir, log_dir, write_logging_manifest):
    return _container_with_logging_manifest(
        manifest_dir,
        write_logging_manifest,
        {"level": "INFO", "console": True, "file": True, "directory": str(log_dir)},
    )


def test_manager_identity():
    manager = LoggingManager()

    assert manager.name == "logging"
    assert manager.dependencies == ()


def test_manager_exposes_a_logging_service_from_construction():
    manager = LoggingManager()

    assert isinstance(manager.service, LoggingService)


def test_health_before_initialize_is_unhealthy():
    manager = LoggingManager()

    assert manager.health().state is HealthState.UNHEALTHY


def test_initialize_registers_the_service_into_the_container(container):
    manager = LoggingManager()
    context = RuntimeContext(services=container)

    manager.initialize(context)

    assert container.has(LoggingService) is True
    assert container.get(LoggingService) is manager.service


def test_initialize_attaches_console_sink_and_health_becomes_healthy(container):
    manager = LoggingManager()
    context = RuntimeContext(services=container)

    manager.initialize(context)

    assert manager.health().state is HealthState.HEALTHY


def test_startup_attaches_file_sink(container, log_dir):
    manager = LoggingManager()
    manager.initialize(RuntimeContext(services=container))

    manager.startup()
    manager.service.info("after startup")

    log_path = log_dir / "heimei.log"
    assert log_path.exists()
    assert "after startup" in log_path.read_text()


def test_log_calls_before_startup_do_not_reach_the_file(container, log_dir):
    manager = LoggingManager()
    manager.initialize(RuntimeContext(services=container))

    manager.service.info("during initialize phase")

    assert not (log_dir / "heimei.log").exists()


def test_shutdown_detaches_both_sinks(container, log_dir):
    manager = LoggingManager()
    manager.initialize(RuntimeContext(services=container))
    manager.startup()

    manager.shutdown()
    log_path = log_dir / "heimei.log"
    size_after_shutdown = log_path.stat().st_size
    manager.service.info("after shutdown, should go nowhere")

    assert manager.health().state is HealthState.UNHEALTHY
    assert log_path.stat().st_size == size_after_shutdown


def test_shutdown_is_safe_to_call_after_only_initialize(container):
    manager = LoggingManager()
    manager.initialize(RuntimeContext(services=container))

    manager.shutdown()  # no startup() was called; must not raise

    assert manager.health().state is HealthState.UNHEALTHY


def test_console_disabled_via_manifest_skips_console_sink(
    manifest_dir, log_dir, write_logging_manifest, capsys
):
    container = _container_with_logging_manifest(
        manifest_dir,
        write_logging_manifest,
        {"level": "INFO", "console": False, "file": True, "directory": str(log_dir)},
    )
    manager = LoggingManager()

    manager.initialize(RuntimeContext(services=container))
    manager.service.info("should not print")

    assert capsys.readouterr().err == ""


def test_console_disabled_removes_any_pre_existing_default_sink(
    manifest_dir, log_dir, write_logging_manifest, capsys
):
    # Simulates loguru's own default stderr sink, present before any Heimei
    # code has run. Without clear_sinks(), console: false never removes it.
    logger.add(sys.stderr, format="{message}")
    container = _container_with_logging_manifest(
        manifest_dir,
        write_logging_manifest,
        {"level": "INFO", "console": False, "file": True, "directory": str(log_dir)},
    )
    manager = LoggingManager()

    manager.initialize(RuntimeContext(services=container))
    manager.service.info("should not print")

    assert capsys.readouterr().err == ""


def test_file_disabled_via_manifest_skips_file_sink(manifest_dir, log_dir, write_logging_manifest):
    container = _container_with_logging_manifest(
        manifest_dir,
        write_logging_manifest,
        {"level": "INFO", "console": True, "file": False, "directory": str(log_dir)},
    )
    manager = LoggingManager()

    manager.initialize(RuntimeContext(services=container))
    manager.startup()
    manager.service.info("should not reach a file")

    assert not (log_dir / "heimei.log").exists()


def test_missing_directory_falls_back_to_heimei_home_state_logs(
    manifest_dir, write_logging_manifest, monkeypatch, tmp_path
):
    monkeypatch.setenv("HEIMEI_HOME", str(tmp_path))
    container = _container_with_logging_manifest(
        manifest_dir,
        write_logging_manifest,
        {"level": "INFO", "console": True, "file": True},
    )
    manager = LoggingManager()

    manager.initialize(RuntimeContext(services=container))
    manager.startup()
    manager.service.info("default location")

    expected_path = tmp_path / "State" / "Logs" / "heimei.log"
    assert expected_path.exists()
    assert "default location" in expected_path.read_text()
