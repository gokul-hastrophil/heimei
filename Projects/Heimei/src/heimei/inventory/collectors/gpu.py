import shutil
import subprocess
from datetime import UTC, datetime

from pydantic import BaseModel

from heimei.inventory.record import InventoryRecord

COLLECTOR_VERSION = "1.0"


class GpuDevice(BaseModel):
    name: str
    memory_total_bytes: int | None = None


class GpuSnapshot(InventoryRecord):
    """See ADR-0013, section 5. ``available=False`` covers "no GPU",
    "GPU tooling not installed", and any discovery failure alike —
    Inventory never raises because a subsystem is absent, it only
    reports facts.
    """

    available: bool
    devices: tuple[GpuDevice, ...]


def _via_pynvml() -> tuple[GpuDevice, ...] | None:
    """None means this mechanism itself couldn't run; an empty tuple
    means it ran but found nothing (still worth trying the next layer,
    since pynvml only ever sees NVIDIA hardware).
    """
    try:
        import pynvml  # type: ignore[import-not-found]
    except ImportError:
        return None
    try:
        pynvml.nvmlInit()
    except Exception:
        return None
    try:
        devices = []
        for index in range(pynvml.nvmlDeviceGetCount()):
            handle = pynvml.nvmlDeviceGetHandleByIndex(index)
            name = pynvml.nvmlDeviceGetName(handle)
            if isinstance(name, bytes):
                name = name.decode()
            memory = pynvml.nvmlDeviceGetMemoryInfo(handle)
            devices.append(GpuDevice(name=name, memory_total_bytes=memory.total))
        return tuple(devices)
    except Exception:
        return None
    finally:
        pynvml.nvmlShutdown()


def _via_nvidia_smi() -> tuple[GpuDevice, ...] | None:
    if shutil.which("nvidia-smi") is None:
        return None
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None

    devices = []
    for line in result.stdout.strip().splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) != 2:
            continue
        name, memory_mib = parts
        try:
            memory_total_bytes = int(float(memory_mib) * 1024 * 1024)
        except ValueError:
            memory_total_bytes = None
        devices.append(GpuDevice(name=name, memory_total_bytes=memory_total_bytes))
    return tuple(devices)


def _via_lspci() -> tuple[GpuDevice, ...] | None:
    if shutil.which("lspci") is None:
        return None
    try:
        result = subprocess.run(
            ["lspci"], capture_output=True, text=True, timeout=5, check=True
        )
    except (OSError, subprocess.SubprocessError):
        return None

    devices = [
        GpuDevice(name=line.split(":", 2)[-1].strip())
        for line in result.stdout.splitlines()
        if "VGA compatible controller" in line or "3D controller" in line
    ]
    return tuple(devices)


def collect() -> GpuSnapshot:
    last_source_that_ran: str | None = None
    for source, mechanism in (
        ("pynvml", _via_pynvml),
        ("nvidia-smi", _via_nvidia_smi),
        ("lspci", _via_lspci),
    ):
        devices = mechanism()
        if devices is None:
            continue
        last_source_that_ran = source
        if devices:
            return GpuSnapshot(
                collected_at=datetime.now(UTC),
                source=source,
                collector_version=COLLECTOR_VERSION,
                available=True,
                devices=devices,
            )

    return GpuSnapshot(
        collected_at=datetime.now(UTC),
        source=last_source_that_ran or "none",
        collector_version=COLLECTOR_VERSION,
        available=False,
        devices=(),
    )
