"""Status: a composed summary of what's happening right now, over
Runtime, Inventory, and Doctor. See ``System/docs/Architecture/
0015-status-manager.md``.

Public contract:

- ``StatusService``: ``snapshot()`` — the only method. Resolves Runtime,
  InventoryService, and DoctorService exactly once, at construction.
- ``StatusManager``: the ``Manager`` lifecycle implementation. Registers
  ``StatusService`` into the ServiceContainer during ``initialize()``.
- ``StatusSnapshot`` and its component models (``RuntimeSummary``,
  ``ManagerSummary``, ``MachineSummary``, ``CpuSummary``,
  ``MemorySummary``, ``StorageSummary``, ``StorageMountSummary``,
  ``NetworkSummary``, ``NetworkInterfaceSummary``, ``GpuSummary``,
  ``DockerSummary``, ``FindingCounts``): the shared, strongly-typed shape
  ``snapshot()`` returns. Every one of these is Status's own model, not
  a re-export of Core Runtime's or Inventory's concrete types — see
  ADR-0015, section 2, for why that's deliberate.

Status never queries the operating system directly, never duplicates an
Inventory collector, and never implements a diagnostic rule — it answers
"what is happening right now?", not "what is wrong?" (that's Doctor's
job). Status never mutates system state.
"""

from heimei.status.manager import StatusManager
from heimei.status.models import (
    CpuSummary,
    DockerSummary,
    FindingCounts,
    GpuSummary,
    MachineSummary,
    ManagerSummary,
    MemorySummary,
    NetworkInterfaceSummary,
    NetworkSummary,
    RuntimeSummary,
    StatusSnapshot,
    StorageMountSummary,
    StorageSummary,
)
from heimei.status.service import StatusService

__all__ = [
    "CpuSummary",
    "DockerSummary",
    "FindingCounts",
    "GpuSummary",
    "MachineSummary",
    "ManagerSummary",
    "MemorySummary",
    "NetworkInterfaceSummary",
    "NetworkSummary",
    "RuntimeSummary",
    "StatusManager",
    "StatusService",
    "StatusSnapshot",
    "StorageMountSummary",
    "StorageSummary",
]
