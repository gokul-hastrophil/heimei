from dataclasses import dataclass
from enum import Enum, auto

from heimei.core.container import ServiceContainer
from heimei.core.context import RuntimeContext
from heimei.core.errors import (
    DependencyCycleError,
    DuplicateManagerError,
    RuntimeStateError,
    UnknownDependencyError,
)
from heimei.core.health import HealthStatus
from heimei.core.manager import Manager


class ManagerState(Enum):
    REGISTERED = "registered"
    INITIALIZED = "initialized"
    STARTED = "started"
    SHUT_DOWN = "shut_down"


class _Phase(Enum):
    NOT_STARTED = auto()
    STARTED = auto()
    SHUT_DOWN = auto()


@dataclass(frozen=True)
class ManagerRecord:
    """A read-only snapshot of one registered manager's status."""

    name: str
    order: int | None
    state: ManagerState
    health: HealthStatus | None


class Runtime:
    """Orchestrates Manager lifecycle. No business logic — see ADR-0011.

    Managers register in any order. Startup order is derived from their
    declared ``dependencies`` via a topological sort; shutdown order is
    its exact reverse. ``initialize()`` runs on every manager before
    ``startup()`` runs on any of them. The registry (``.managers``) is
    read-only: it can be queried, never mutated directly.
    """

    def __init__(self, container: ServiceContainer):
        self._container = container
        self._managers: dict[str, Manager] = {}
        self._states: dict[str, ManagerState] = {}
        self._order: list[str] | None = None
        self._phase = _Phase.NOT_STARTED

    def register(self, manager: Manager) -> None:
        if self._phase is not _Phase.NOT_STARTED:
            raise RuntimeStateError("Cannot register a manager after the Runtime has started")
        if manager.name in self._managers:
            raise DuplicateManagerError(manager.name)
        self._managers[manager.name] = manager
        self._states[manager.name] = ManagerState.REGISTERED

    def startup(self) -> None:
        if self._phase is not _Phase.NOT_STARTED:
            raise RuntimeStateError("Runtime has already been started")

        order = self._resolve_order()
        context = RuntimeContext(services=self._container)

        for name in order:
            self._managers[name].initialize(context)
            self._states[name] = ManagerState.INITIALIZED

        for name in order:
            self._managers[name].startup()
            self._states[name] = ManagerState.STARTED

        self._order = order
        self._phase = _Phase.STARTED

    def shutdown(self) -> None:
        if self._phase is not _Phase.STARTED:
            raise RuntimeStateError("Runtime has not been started")

        assert self._order is not None
        for name in reversed(self._order):
            self._managers[name].shutdown()
            self._states[name] = ManagerState.SHUT_DOWN

        self._phase = _Phase.SHUT_DOWN

    @property
    def managers(self) -> tuple[ManagerRecord, ...]:
        """A read-only snapshot: name, resolved order, lifecycle state, live health()."""
        order_index = {name: i for i, name in enumerate(self._order)} if self._order else {}
        records = []
        for name, manager in self._managers.items():
            state = self._states[name]
            health = manager.health() if state is not ManagerState.REGISTERED else None
            records.append(
                ManagerRecord(name=name, order=order_index.get(name), state=state, health=health)
            )
        return tuple(records)

    def _resolve_order(self) -> list[str]:
        for name, manager in self._managers.items():
            for dependency in manager.dependencies:
                if dependency not in self._managers:
                    raise UnknownDependencyError(name, dependency)

        remaining = dict(self._managers)
        resolved: list[str] = []
        resolved_set: set[str] = set()

        while remaining:
            ready = [
                name
                for name, manager in remaining.items()
                if all(dep in resolved_set for dep in manager.dependencies)
            ]
            if not ready:
                raise DependencyCycleError(tuple(remaining.keys()))
            for name in ready:
                resolved.append(name)
                resolved_set.add(name)
                del remaining[name]

        return resolved
