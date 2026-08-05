from pydantic import BaseModel


class ManagerSummary(BaseModel):
    """One Runtime-registered manager's identity, order, lifecycle state,
    and live health.

    Deliberately its own model rather than embedding Core Runtime's own
    ``ManagerRecord`` directly — see ADR-0015, section 2.
    """

    name: str
    order: int | None
    lifecycle_state: str
    health_state: str | None
    health_detail: str | None


class RuntimeSummary(BaseModel):
    """What the Runtime is doing right now — not a health judgment."""

    manager_count: int
    all_managers_started: bool
    managers: tuple[ManagerSummary, ...]


class MachineSummary(BaseModel):
    hostname: str
    system: str
    release: str
    architecture: str


class CpuSummary(BaseModel):
    logical_cores: int
    physical_cores: int | None
    max_frequency_mhz: float | None


class MemorySummary(BaseModel):
    total_bytes: int
    available_bytes: int
    percent: float


class StorageMountSummary(BaseModel):
    path: str
    total_bytes: int
    free_bytes: int
    percent: float


class StorageSummary(BaseModel):
    mounts: tuple[StorageMountSummary, ...]


class NetworkInterfaceSummary(BaseModel):
    name: str
    address_count: int


class NetworkSummary(BaseModel):
    interfaces: tuple[NetworkInterfaceSummary, ...]


class GpuSummary(BaseModel):
    available: bool
    source: str
    device_names: tuple[str, ...]


class DockerSummary(BaseModel):
    available: bool
    version: str | None
    source: str


class FindingCounts(BaseModel):
    """A tally of Doctor's own Findings by severity. Doctor already
    judged each one; this only counts — see ADR-0015, section 1.
    """

    ok: int
    warning: int
    critical: int


class StatusSnapshot(BaseModel):
    """Answers "what is happening right now?" — never "what is wrong?"
    (that's Doctor's job; see ADR-0015). Every field is data already
    produced by Runtime, InventoryService, or DoctorService — copied
    across field-by-field in ``StatusService``, never by embedding those
    subsystems' own concrete types here. That keeps this module free of
    any cross-package import at all, deliberately: see ADR-0015, section
    2, on why that also matters for load-order safety, not just style.
    """

    runtime: RuntimeSummary
    machine: MachineSummary
    cpu: CpuSummary
    memory: MemorySummary
    storage: StorageSummary
    network: NetworkSummary
    gpu: GpuSummary
    docker: DockerSummary
    findings: FindingCounts
