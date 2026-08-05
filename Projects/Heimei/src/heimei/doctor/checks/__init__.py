"""Independent, single-responsibility health checks.

Each module exposes one class satisfying ``heimei.doctor.base.HealthCheck``
(``name``, ``category``, ``run(inventory) -> tuple[Finding, ...]``). A
check never imports another check, never imports ``DoctorService`` or
``CheckRegistry``, and never touches the operating system, ``psutil``,
or anything else directly — only ``InventoryService``. See ADR-0014.
"""

from heimei.doctor.checks.cpu import CpuCheck
from heimei.doctor.checks.docker import DockerCheck
from heimei.doctor.checks.gpu import GpuCheck
from heimei.doctor.checks.memory import MemoryCheck
from heimei.doctor.checks.network import NetworkCheck
from heimei.doctor.checks.storage import StorageCheck

__all__ = [
    "CpuCheck",
    "DockerCheck",
    "GpuCheck",
    "MemoryCheck",
    "NetworkCheck",
    "StorageCheck",
]
