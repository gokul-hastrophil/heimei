from __future__ import annotations

from typing import TYPE_CHECKING

from heimei.doctor.base import Severity
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

if TYPE_CHECKING:
    from heimei.core import Runtime
    from heimei.doctor import DoctorService
    from heimei.inventory import InventoryService


class StatusService:
    """Answers "what is happening right now?" — never "what is wrong?"
    (that's DoctorService's job; see ADR-0015, section 1). A pure
    aggregator over Runtime, InventoryService, and DoctorService: no OS
    access, no diagnostic rules, no mutation, no collector of its own.
    Resolves all three exactly once, at construction, the same pattern
    DoctorService uses for InventoryService.

    Reads every Inventory snapshot and Runtime record structurally
    (attribute access only) rather than importing their concrete types —
    the same "read data, don't import the producer's type" pattern
    Doctor's own checks already use for Inventory. See ADR-0015, section
    2: this is what keeps ``heimei.status`` free of any module-level
    ``heimei.core``/``heimei.inventory`` import, not just a style choice.
    """

    def __init__(
        self, runtime: Runtime, inventory: InventoryService, doctor: DoctorService
    ) -> None:
        self._runtime = runtime
        self._inventory = inventory
        self._doctor = doctor

    def snapshot(self) -> StatusSnapshot:
        """A fresh view of the machine and the running process.

        Requests a refreshed Inventory read for every volatile category
        (memory/storage/network/gpu/docker) — a status view that quietly
        reused stale cached data would defeat its own purpose. Runs every
        registered Doctor check to get current finding counts; does not
        interpret or filter them itself.
        """
        managers = tuple(
            ManagerSummary(
                name=record.name,
                order=record.order,
                lifecycle_state=record.state.value,
                health_state=record.health.state.value if record.health else None,
                health_detail=record.health.detail if record.health else None,
            )
            for record in self._runtime.managers
        )

        machine = self._inventory.machine()
        cpu = self._inventory.cpu()
        memory = self._inventory.memory(refresh=True)
        storage = self._inventory.storage(refresh=True)
        network = self._inventory.network(refresh=True)
        gpu = self._inventory.gpu(refresh=True)
        docker = self._inventory.docker(refresh=True)

        findings = self._doctor.run()
        counts = FindingCounts(
            ok=sum(1 for finding in findings if finding.severity is Severity.OK),
            warning=sum(1 for finding in findings if finding.severity is Severity.WARNING),
            critical=sum(1 for finding in findings if finding.severity is Severity.CRITICAL),
        )

        return StatusSnapshot(
            runtime=RuntimeSummary(
                manager_count=len(managers),
                # Compared against ManagerState.STARTED's literal value
                # rather than importing that enum — see ADR-0015, section 2.
                all_managers_started=all(m.lifecycle_state == "started" for m in managers),
                managers=managers,
            ),
            machine=MachineSummary(
                hostname=machine.hostname,
                system=machine.system,
                release=machine.release,
                architecture=machine.architecture,
            ),
            cpu=CpuSummary(
                logical_cores=cpu.logical_cores,
                physical_cores=cpu.physical_cores,
                max_frequency_mhz=cpu.max_frequency_mhz,
            ),
            memory=MemorySummary(
                total_bytes=memory.total_bytes,
                available_bytes=memory.available_bytes,
                percent=memory.percent,
            ),
            storage=StorageSummary(
                mounts=tuple(
                    StorageMountSummary(
                        path=mount.path,
                        total_bytes=mount.total_bytes,
                        free_bytes=mount.free_bytes,
                        percent=mount.percent,
                    )
                    for mount in storage.mounts
                ),
            ),
            network=NetworkSummary(
                interfaces=tuple(
                    NetworkInterfaceSummary(
                        name=interface.name, address_count=len(interface.addresses)
                    )
                    for interface in network.interfaces
                ),
            ),
            gpu=GpuSummary(
                available=gpu.available,
                source=gpu.source,
                device_names=tuple(device.name for device in gpu.devices),
            ),
            docker=DockerSummary(
                available=docker.available,
                version=docker.version,
                source=docker.source,
            ),
            findings=counts,
        )
