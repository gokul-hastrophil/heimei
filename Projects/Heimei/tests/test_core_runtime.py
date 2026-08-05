import pytest

from heimei.core.container import ServiceContainer
from heimei.core.errors import (
    DependencyCycleError,
    DuplicateManagerError,
    RuntimeStateError,
    UnknownDependencyError,
)
from heimei.core.health import HealthState, HealthStatus
from heimei.core.runtime import ManagerState, Runtime


class FakeManager:
    """A Manager test double that records every lifecycle call it receives."""

    def __init__(self, name, dependencies=(), call_log=None, health_state=HealthState.HEALTHY):
        self.name = name
        self.dependencies = dependencies
        self.call_log = call_log if call_log is not None else []
        self.context = None
        self.health_state = health_state
        self.fail_on = set()

    def initialize(self, context):
        if "initialize" in self.fail_on:
            raise RuntimeError(f"{self.name} failed to initialize")
        self.context = context
        self.call_log.append((self.name, "initialize"))

    def startup(self):
        if "startup" in self.fail_on:
            raise RuntimeError(f"{self.name} failed to start")
        self.call_log.append((self.name, "startup"))

    def health(self):
        return HealthStatus(state=self.health_state)

    def shutdown(self):
        if "shutdown" in self.fail_on:
            raise RuntimeError(f"{self.name} failed to shut down")
        self.call_log.append((self.name, "shutdown"))


@pytest.fixture
def container():
    return ServiceContainer()


def test_register_reports_registered_state_with_no_order_or_health(container):
    runtime = Runtime(container)
    runtime.register(FakeManager("a"))

    (record,) = runtime.managers

    assert record.name == "a"
    assert record.order is None
    assert record.state is ManagerState.REGISTERED
    assert record.health is None


def test_duplicate_manager_name_raises(container):
    runtime = Runtime(container)
    runtime.register(FakeManager("a"))

    with pytest.raises(DuplicateManagerError):
        runtime.register(FakeManager("a"))


def test_startup_with_zero_managers_succeeds(container):
    runtime = Runtime(container)

    runtime.startup()

    assert runtime.managers == ()


def test_all_managers_initialize_before_any_manager_starts(container):
    log = []
    runtime = Runtime(container)
    runtime.register(FakeManager("a", call_log=log))
    runtime.register(FakeManager("b", call_log=log))

    runtime.startup()

    last_initialize_index = max(i for i, (_, phase) in enumerate(log) if phase == "initialize")
    first_startup_index = min(i for i, (_, phase) in enumerate(log) if phase == "startup")
    assert last_initialize_index < first_startup_index


def test_context_passed_to_initialize_carries_the_container(container):
    runtime = Runtime(container)
    manager = FakeManager("a")
    runtime.register(manager)

    runtime.startup()

    assert manager.context.services is container


def test_linear_dependency_chain_is_ordered_correctly(container):
    log = []
    runtime = Runtime(container)
    runtime.register(FakeManager("c", dependencies=("b",), call_log=log))
    runtime.register(FakeManager("a", call_log=log))
    runtime.register(FakeManager("b", dependencies=("a",), call_log=log))

    runtime.startup()

    initialize_order = [name for name, phase in log if phase == "initialize"]
    assert initialize_order == ["a", "b", "c"]

    records = {r.name: r.order for r in runtime.managers}
    assert records["a"] < records["b"] < records["c"]


def test_diamond_dependency_resolves_deterministically(container):
    log = []
    runtime = Runtime(container)
    runtime.register(FakeManager("a", call_log=log))
    runtime.register(FakeManager("b", dependencies=("a",), call_log=log))
    runtime.register(FakeManager("c", dependencies=("a",), call_log=log))
    runtime.register(FakeManager("d", dependencies=("b", "c"), call_log=log))

    runtime.startup()

    initialize_order = [name for name, phase in log if phase == "initialize"]
    assert initialize_order == ["a", "b", "c", "d"]


def test_unknown_dependency_raises_and_no_manager_is_initialized(container):
    log = []
    runtime = Runtime(container)
    runtime.register(FakeManager("a", dependencies=("ghost",), call_log=log))

    with pytest.raises(UnknownDependencyError):
        runtime.startup()

    assert log == []


def test_dependency_cycle_raises_and_no_manager_is_initialized(container):
    log = []
    runtime = Runtime(container)
    runtime.register(FakeManager("a", dependencies=("b",), call_log=log))
    runtime.register(FakeManager("b", dependencies=("a",), call_log=log))

    with pytest.raises(DependencyCycleError):
        runtime.startup()

    assert log == []


def test_shutdown_runs_in_reverse_order(container):
    log = []
    runtime = Runtime(container)
    runtime.register(FakeManager("a", call_log=log))
    runtime.register(FakeManager("b", dependencies=("a",), call_log=log))
    runtime.register(FakeManager("c", dependencies=("b",), call_log=log))
    runtime.startup()
    log.clear()

    runtime.shutdown()

    shutdown_order = [name for name, phase in log if phase == "shutdown"]
    assert shutdown_order == ["c", "b", "a"]


def test_shutdown_updates_manager_state(container):
    runtime = Runtime(container)
    runtime.register(FakeManager("a"))
    runtime.startup()

    runtime.shutdown()

    (record,) = runtime.managers
    assert record.state is ManagerState.SHUT_DOWN


def test_shutdown_before_startup_raises(container):
    runtime = Runtime(container)
    runtime.register(FakeManager("a"))

    with pytest.raises(RuntimeStateError):
        runtime.shutdown()


def test_startup_called_twice_raises(container):
    runtime = Runtime(container)
    runtime.register(FakeManager("a"))
    runtime.startup()

    with pytest.raises(RuntimeStateError):
        runtime.startup()


def test_shutdown_called_twice_raises(container):
    runtime = Runtime(container)
    runtime.register(FakeManager("a"))
    runtime.startup()
    runtime.shutdown()

    with pytest.raises(RuntimeStateError):
        runtime.shutdown()


def test_register_after_startup_raises(container):
    runtime = Runtime(container)
    runtime.register(FakeManager("a"))
    runtime.startup()

    with pytest.raises(RuntimeStateError):
        runtime.register(FakeManager("b"))


def test_managers_reflects_live_health_not_a_cached_snapshot(container):
    runtime = Runtime(container)
    manager = FakeManager("a")
    runtime.register(manager)
    runtime.startup()

    (before,) = runtime.managers
    assert before.health.state is HealthState.HEALTHY

    manager.health_state = HealthState.UNHEALTHY
    (after,) = runtime.managers
    assert after.health.state is HealthState.UNHEALTHY


def test_initialize_failure_propagates_and_stops_further_initialization(container):
    log = []
    runtime = Runtime(container)
    failing = FakeManager("a", call_log=log)
    failing.fail_on.add("initialize")
    runtime.register(failing)
    runtime.register(FakeManager("b", dependencies=("a",), call_log=log))

    with pytest.raises(RuntimeError, match="failed to initialize"):
        runtime.startup()

    assert log == []


def test_startup_failure_propagates_and_stops_further_activation(container):
    log = []
    runtime = Runtime(container)
    failing = FakeManager("a", call_log=log)
    failing.fail_on.add("startup")
    runtime.register(failing)
    runtime.register(FakeManager("b", dependencies=("a",), call_log=log))

    with pytest.raises(RuntimeError, match="failed to start"):
        runtime.startup()

    # both managers initialized (phase 1 completed), but b never started
    assert ("a", "initialize") in log
    assert ("b", "initialize") in log
    assert ("b", "startup") not in log


def test_shutdown_failure_propagates_and_stops_further_shutdown(container):
    log = []
    runtime = Runtime(container)
    runtime.register(FakeManager("a", call_log=log))
    failing = FakeManager("b", dependencies=("a",), call_log=log)
    runtime.register(failing)
    runtime.startup()
    log.clear()
    failing.fail_on.add("shutdown")

    with pytest.raises(RuntimeError, match="failed to shut down"):
        runtime.shutdown()

    # b shuts down first (reverse order) and fails; a never gets shutdown
    assert ("a", "shutdown") not in log


def test_startup_failure_shuts_down_already_started_managers_in_reverse_order(container):
    log = []
    runtime = Runtime(container)
    runtime.register(FakeManager("a", call_log=log))
    runtime.register(FakeManager("b", dependencies=("a",), call_log=log))
    failing = FakeManager("c", dependencies=("b",), call_log=log)
    failing.fail_on.add("startup")
    runtime.register(failing)

    with pytest.raises(RuntimeError, match="failed to start"):
        runtime.startup()

    shutdown_order = [name for name, phase in log if phase == "shutdown"]
    assert shutdown_order == ["b", "a"]


def test_retrying_startup_after_a_failure_raises_instead_of_reinitializing(container):
    log = []
    runtime = Runtime(container)
    failing = FakeManager("a", call_log=log)
    failing.fail_on.add("startup")
    runtime.register(failing)

    with pytest.raises(RuntimeError, match="failed to start"):
        runtime.startup()

    with pytest.raises(RuntimeStateError):
        runtime.startup()


def test_shutdown_after_a_failed_startup_raises(container):
    runtime = Runtime(container)
    failing = FakeManager("a")
    failing.fail_on.add("startup")
    runtime.register(failing)

    with pytest.raises(RuntimeError, match="failed to start"):
        runtime.startup()

    with pytest.raises(RuntimeStateError):
        runtime.shutdown()


def test_managers_view_is_an_immutable_tuple(container):
    runtime = Runtime(container)
    runtime.register(FakeManager("a"))

    assert isinstance(runtime.managers, tuple)
