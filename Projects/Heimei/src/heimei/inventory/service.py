from heimei.inventory.collectors import cpu, docker, gpu, machine, memory, network, python, storage
from heimei.inventory.collectors.cpu import CpuSnapshot
from heimei.inventory.collectors.docker import DockerSnapshot
from heimei.inventory.collectors.gpu import GpuSnapshot
from heimei.inventory.collectors.machine import MachineSnapshot
from heimei.inventory.collectors.memory import MemorySnapshot
from heimei.inventory.collectors.network import NetworkSnapshot
from heimei.inventory.collectors.python import PythonSnapshot
from heimei.inventory.collectors.storage import StorageSnapshot


class InventoryService:
    """The single source of truth for live machine state. See ADR-0013.

    A façade over independent collectors (``heimei.inventory.collectors``).
    Caching is entirely internal: ``machine()``/``cpu()``/``python()``
    collect once and cache forever (there is nothing to refresh); the
    rest collect on first use and again whenever ``refresh=True``.
    """

    def __init__(self) -> None:
        self._machine: MachineSnapshot | None = None
        self._cpu: CpuSnapshot | None = None
        self._python: PythonSnapshot | None = None
        self._memory: MemorySnapshot | None = None
        self._storage: StorageSnapshot | None = None
        self._network: NetworkSnapshot | None = None
        self._gpu: GpuSnapshot | None = None
        self._docker: DockerSnapshot | None = None

    def machine(self) -> MachineSnapshot:
        if self._machine is None:
            self._machine = machine.collect()
        return self._machine

    def cpu(self) -> CpuSnapshot:
        if self._cpu is None:
            self._cpu = cpu.collect()
        return self._cpu

    def python(self) -> PythonSnapshot:
        if self._python is None:
            self._python = python.collect()
        return self._python

    def memory(self, *, refresh: bool = False) -> MemorySnapshot:
        if self._memory is None or refresh:
            self._memory = memory.collect()
        return self._memory

    def storage(self, *, refresh: bool = False) -> StorageSnapshot:
        if self._storage is None or refresh:
            self._storage = storage.collect()
        return self._storage

    def network(self, *, refresh: bool = False) -> NetworkSnapshot:
        if self._network is None or refresh:
            self._network = network.collect()
        return self._network

    def gpu(self, *, refresh: bool = False) -> GpuSnapshot:
        if self._gpu is None or refresh:
            self._gpu = gpu.collect()
        return self._gpu

    def docker(self, *, refresh: bool = False) -> DockerSnapshot:
        if self._docker is None or refresh:
            self._docker = docker.collect()
        return self._docker
