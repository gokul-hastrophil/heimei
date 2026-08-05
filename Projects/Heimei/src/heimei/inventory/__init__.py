"""Inventory Manager: the single source of truth for live machine state.

See ``System/docs/Architecture/0013-inventory-manager.md``. Public
contract:

- ``InventoryService``: the façade — ``machine()``, ``cpu()``,
  ``python()`` (no ``refresh``, cached forever), and ``memory()``,
  ``storage()``, ``network()``, ``gpu()``, ``docker()`` (each accepts
  ``refresh: bool = False``). Every method returns a strongly typed
  Snapshot model. Resolve it with ``context.services.get(InventoryService)``
  — never call ``psutil``, ``platform``, or shell out to GPU/Docker
  tooling directly.
- ``InventoryManager``: the ``Manager`` lifecycle implementation.
  Registers ``InventoryService`` into the ``ServiceContainer`` during
  ``initialize()``.
- ``InventoryRecord``: the shared metadata base every Snapshot inherits
  (``collected_at``, ``source``, ``collector_version``).

Nothing outside ``heimei.inventory.collectors`` touches ``psutil``,
``platform``, ``pynvml``, or shells out to ``nvidia-smi``/``lspci``/
``docker``. Collectors never know about each other or about
``InventoryService``.

Inventory is consumed by Status, Doctor, and future managers; it never
consumes them.
"""

from heimei.inventory.collectors.cpu import CpuSnapshot
from heimei.inventory.collectors.docker import DockerSnapshot
from heimei.inventory.collectors.gpu import GpuDevice, GpuSnapshot
from heimei.inventory.collectors.machine import MachineSnapshot
from heimei.inventory.collectors.memory import MemorySnapshot
from heimei.inventory.collectors.network import NetworkInterface, NetworkSnapshot
from heimei.inventory.collectors.python import PythonSnapshot
from heimei.inventory.collectors.storage import StorageMount, StorageSnapshot
from heimei.inventory.manager import InventoryManager
from heimei.inventory.record import InventoryRecord
from heimei.inventory.service import InventoryService

__all__ = [
    "CpuSnapshot",
    "DockerSnapshot",
    "GpuDevice",
    "GpuSnapshot",
    "InventoryManager",
    "InventoryRecord",
    "InventoryService",
    "MachineSnapshot",
    "MemorySnapshot",
    "NetworkInterface",
    "NetworkSnapshot",
    "PythonSnapshot",
    "StorageMount",
    "StorageSnapshot",
]
