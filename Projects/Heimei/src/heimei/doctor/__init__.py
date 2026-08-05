"""Doctor: a rule engine that evaluates Inventory snapshots and produces
findings. See ``System/docs/Architecture/0014-doctor-manager.md``.

Public contract:

- ``DoctorService``: ``register(check)``, ``run(category=)``, ``run(check=)``.
  Resolves ``InventoryService`` exactly once, at construction.
- ``DoctorManager``: the ``Manager`` lifecycle implementation. Registers
  every built-in check explicitly — no auto-discovery, no plugins.
- ``Severity``, ``Category``, ``Finding``, ``HealthCheck``: the shared
  contract every check and finding uses.

Doctor never queries the operating system directly — only
``InventoryService`` does that — and never mutates system state.
"""

from heimei.doctor.base import (
    Category,
    CheckNotFoundError,
    DoctorError,
    DuplicateCheckError,
    Finding,
    HealthCheck,
    Severity,
)
from heimei.doctor.manager import DoctorManager
from heimei.doctor.service import DoctorService

__all__ = [
    "Category",
    "CheckNotFoundError",
    "DoctorError",
    "DuplicateCheckError",
    "Finding",
    "HealthCheck",
    "Severity",
    "DoctorManager",
    "DoctorService",
]
