"""Core Runtime: orchestration layer for Heimei's managers.

See ``System/docs/Architecture/0011-core-runtime.md``. Public contract:

- ``Application``: minimal bootstrap (ServiceContainer + Configuration + Runtime).
- ``ServiceContainer``: ``register``/``get``/``has``, nothing more.
- ``Runtime``: register managers, derive dependency order, drive their
  lifecycle, expose a read-only registry. No business logic.
- ``Manager``: the ``initialize``/``startup``/``health``/``shutdown``
  protocol every manager implements, plus declared ``dependencies``.
- ``RuntimeContext``: the single object passed to ``initialize()``.
- ``HealthState``/``HealthStatus``: the frozen health-reporting interface.

The errors below (``CoreError`` and subclasses) give dependency and
lifecycle-misuse problems a specific, named cause rather than a bare
``KeyError``/``AttributeError``.
"""

from heimei.core.application import Application
from heimei.core.container import ServiceContainer
from heimei.core.context import RuntimeContext
from heimei.core.errors import (
    CoreError,
    DependencyCycleError,
    DuplicateManagerError,
    RuntimeStateError,
    ServiceAlreadyRegisteredError,
    ServiceNotRegisteredError,
    UnknownDependencyError,
)
from heimei.core.health import HealthState, HealthStatus
from heimei.core.manager import Manager
from heimei.core.runtime import ManagerRecord, ManagerState, Runtime

__all__ = [
    "Application",
    "ServiceContainer",
    "RuntimeContext",
    "CoreError",
    "DependencyCycleError",
    "DuplicateManagerError",
    "RuntimeStateError",
    "ServiceAlreadyRegisteredError",
    "ServiceNotRegisteredError",
    "UnknownDependencyError",
    "HealthState",
    "HealthStatus",
    "Manager",
    "ManagerRecord",
    "ManagerState",
    "Runtime",
]
