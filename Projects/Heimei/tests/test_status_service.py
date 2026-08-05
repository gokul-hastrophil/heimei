from datetime import UTC, datetime

from heimei.doctor.base import Category, Finding, Severity
from heimei.inventory import (
    CpuSnapshot,
    DockerSnapshot,
    GpuDevice,
    GpuSnapshot,
    MachineSnapshot,
    MemorySnapshot,
    NetworkInterface,
    NetworkSnapshot,
    StorageMount,
    StorageSnapshot,
)
from heimei.status.service import StatusService

NOW = datetime.now(UTC)


class FakeHealthState:
    def __init__(self, value):
        self.value = value


class FakeHealthStatus:
    def __init__(self, value, detail=None):
        self.state = FakeHealthState(value)
        self.detail = detail


class FakeManagerRecord:
    def __init__(self, name, order, state_value, health=None):
        self.name = name
        self.order = order
        self.state = FakeHealthState(state_value)
        self.health = health


class FakeRuntime:
    def __init__(self, managers):
        self.managers = tuple(managers)


class FakeInventory:
    """Matches InventoryService's real signatures exactly: machine()/cpu()
    take no refresh kwarg at all, so a StatusService bug that mistakenly
    passed refresh=True to either would raise TypeError here, same as
    against the real service.
    """

    def __init__(self, *, gpu_available=True, docker_available=True):
        self.refresh_requested = {}
        self._machine = MachineSnapshot(
            collected_at=NOW, source="fake", collector_version="1.0",
            hostname="testhost", system="Linux", release="1.0", architecture="x86_64",
        )
        self._cpu = CpuSnapshot(
            collected_at=NOW, source="fake", collector_version="1.0",
            logical_cores=8, physical_cores=4, max_frequency_mhz=3200.0,
        )
        self._memory = MemorySnapshot(
            collected_at=NOW, source="fake", collector_version="1.0",
            total_bytes=16_000_000_000, available_bytes=8_000_000_000, percent=50.0,
        )
        root_mount = StorageMount(
            path="/", total_bytes=100_000_000_000, free_bytes=50_000_000_000, percent=50.0
        )
        self._storage = StorageSnapshot(
            collected_at=NOW, source="fake", collector_version="1.0", mounts=(root_mount,)
        )
        self._network = NetworkSnapshot(
            collected_at=NOW, source="fake", collector_version="1.0",
            interfaces=(NetworkInterface(name="eth0", addresses=("10.0.0.5",)),),
        )
        gpu_devices = (GpuDevice(name="Fake GPU", memory_total_bytes=4_000_000_000),)
        self._gpu = GpuSnapshot(
            collected_at=NOW, source="fake", collector_version="1.0",
            available=gpu_available, devices=gpu_devices if gpu_available else (),
        )
        self._docker = DockerSnapshot(
            collected_at=NOW, source="fake", collector_version="1.0",
            available=docker_available, version="27.0.0" if docker_available else None,
        )

    def machine(self):
        return self._machine

    def cpu(self):
        return self._cpu

    def memory(self, *, refresh=False):
        self.refresh_requested["memory"] = refresh
        return self._memory

    def storage(self, *, refresh=False):
        self.refresh_requested["storage"] = refresh
        return self._storage

    def network(self, *, refresh=False):
        self.refresh_requested["network"] = refresh
        return self._network

    def gpu(self, *, refresh=False):
        self.refresh_requested["gpu"] = refresh
        return self._gpu

    def docker(self, *, refresh=False):
        self.refresh_requested["docker"] = refresh
        return self._docker


class FakeDoctor:
    def __init__(self, findings):
        self._findings = tuple(findings)

    def run(self):
        return self._findings


def _finding(severity):
    return Finding(
        check="Fake", category=Category.HARDWARE, severity=severity, message="x", evaluated_at=NOW
    )


def test_snapshot_maps_manager_records_into_manager_summaries():
    runtime = FakeRuntime(
        [FakeManagerRecord("logging", 0, "started", FakeHealthStatus("healthy"))]
    )
    service = StatusService(runtime, FakeInventory(), FakeDoctor([]))

    snapshot = service.snapshot()

    (manager,) = snapshot.runtime.managers
    assert manager.name == "logging"
    assert manager.order == 0
    assert manager.lifecycle_state == "started"
    assert manager.health_state == "healthy"
    assert manager.health_detail is None


def test_snapshot_manager_with_no_health_yet_reports_none():
    runtime = FakeRuntime([FakeManagerRecord("logging", None, "registered", health=None)])
    service = StatusService(runtime, FakeInventory(), FakeDoctor([]))

    snapshot = service.snapshot()

    (manager,) = snapshot.runtime.managers
    assert manager.health_state is None
    assert manager.health_detail is None


def test_snapshot_manager_health_detail_is_preserved():
    health = FakeHealthStatus("unhealthy", "doctor is not active")
    runtime = FakeRuntime([FakeManagerRecord("doctor", 2, "started", health)])
    service = StatusService(runtime, FakeInventory(), FakeDoctor([]))

    snapshot = service.snapshot()

    (manager,) = snapshot.runtime.managers
    assert manager.health_detail == "doctor is not active"


def test_snapshot_all_managers_started_true_when_every_manager_started():
    runtime = FakeRuntime(
        [
            FakeManagerRecord("logging", 0, "started"),
            FakeManagerRecord("status", 1, "started"),
        ]
    )
    service = StatusService(runtime, FakeInventory(), FakeDoctor([]))

    snapshot = service.snapshot()

    assert snapshot.runtime.all_managers_started is True
    assert snapshot.runtime.manager_count == 2


def test_snapshot_all_managers_started_false_when_any_manager_not_started():
    runtime = FakeRuntime(
        [
            FakeManagerRecord("logging", 0, "started"),
            FakeManagerRecord("status", None, "registered"),
        ]
    )
    service = StatusService(runtime, FakeInventory(), FakeDoctor([]))

    snapshot = service.snapshot()

    assert snapshot.runtime.all_managers_started is False


def test_snapshot_copies_every_inventory_field_into_its_own_summary_models():
    """StatusSnapshot never embeds Inventory's concrete Snapshot types
    (see ADR-0015, section 2) — this checks every field survives the
    copy into Status's own models, not just that *some* data arrives.
    """
    inventory = FakeInventory()
    service = StatusService(FakeRuntime([]), inventory, FakeDoctor([]))

    snapshot = service.snapshot()

    assert snapshot.machine.hostname == inventory._machine.hostname
    assert snapshot.machine.system == inventory._machine.system
    assert snapshot.machine.release == inventory._machine.release
    assert snapshot.machine.architecture == inventory._machine.architecture

    assert snapshot.cpu.logical_cores == inventory._cpu.logical_cores
    assert snapshot.cpu.physical_cores == inventory._cpu.physical_cores
    assert snapshot.cpu.max_frequency_mhz == inventory._cpu.max_frequency_mhz

    assert snapshot.memory.total_bytes == inventory._memory.total_bytes
    assert snapshot.memory.available_bytes == inventory._memory.available_bytes
    assert snapshot.memory.percent == inventory._memory.percent

    (mount,) = snapshot.storage.mounts
    (real_mount,) = inventory._storage.mounts
    assert mount.path == real_mount.path
    assert mount.total_bytes == real_mount.total_bytes
    assert mount.free_bytes == real_mount.free_bytes
    assert mount.percent == real_mount.percent

    (interface,) = snapshot.network.interfaces
    (real_interface,) = inventory._network.interfaces
    assert interface.name == real_interface.name
    assert interface.address_count == len(real_interface.addresses)

    assert snapshot.gpu.available == inventory._gpu.available
    assert snapshot.gpu.source == inventory._gpu.source
    assert snapshot.gpu.device_names == tuple(d.name for d in inventory._gpu.devices)

    assert snapshot.docker.available == inventory._docker.available
    assert snapshot.docker.version == inventory._docker.version
    assert snapshot.docker.source == inventory._docker.source


def test_snapshot_requests_refreshed_reads_for_every_volatile_category():
    inventory = FakeInventory()
    service = StatusService(FakeRuntime([]), inventory, FakeDoctor([]))

    service.snapshot()

    assert inventory.refresh_requested == {
        "memory": True,
        "storage": True,
        "network": True,
        "gpu": True,
        "docker": True,
    }


def test_snapshot_tallies_doctor_findings_by_severity():
    findings = [
        _finding(Severity.OK),
        _finding(Severity.OK),
        _finding(Severity.OK),
        _finding(Severity.WARNING),
        _finding(Severity.WARNING),
        _finding(Severity.CRITICAL),
    ]
    service = StatusService(FakeRuntime([]), FakeInventory(), FakeDoctor(findings))

    snapshot = service.snapshot()

    assert snapshot.findings.ok == 3
    assert snapshot.findings.warning == 2
    assert snapshot.findings.critical == 1


def test_snapshot_with_no_findings_reports_zero_counts():
    service = StatusService(FakeRuntime([]), FakeInventory(), FakeDoctor([]))

    snapshot = service.snapshot()

    assert snapshot.findings.ok == 0
    assert snapshot.findings.warning == 0
    assert snapshot.findings.critical == 0


def test_snapshot_never_interprets_findings_only_counts_them():
    """A critical finding must not change anything about the runtime or
    machine sections — Status counts, it never judges.
    """
    service = StatusService(
        FakeRuntime([FakeManagerRecord("logging", 0, "started")]),
        FakeInventory(),
        FakeDoctor([_finding(Severity.CRITICAL)]),
    )

    snapshot = service.snapshot()

    assert snapshot.runtime.all_managers_started is True
    assert snapshot.findings.critical == 1


def test_snapshot_when_gpu_unavailable_still_produces_a_snapshot():
    service = StatusService(
        FakeRuntime([]), FakeInventory(gpu_available=False), FakeDoctor([])
    )

    snapshot = service.snapshot()

    assert snapshot.gpu.available is False
    assert snapshot.gpu.device_names == ()


def test_snapshot_when_docker_unavailable_still_produces_a_snapshot():
    service = StatusService(
        FakeRuntime([]), FakeInventory(docker_available=False), FakeDoctor([])
    )

    snapshot = service.snapshot()

    assert snapshot.docker.available is False
    assert snapshot.docker.version is None
