from datetime import UTC, datetime

import psutil

from heimei.inventory.record import InventoryRecord

COLLECTOR_VERSION = "1.0"


class CpuSnapshot(InventoryRecord):
    """Structural CPU facts. No ``refresh`` on this collector (ADR-0013,
    section 2) — core counts and max frequency don't change within a
    process's lifetime, so there is nothing live here to report.
    """

    logical_cores: int
    physical_cores: int | None
    max_frequency_mhz: float | None


def collect() -> CpuSnapshot:
    try:
        frequency = psutil.cpu_freq()
    except NotImplementedError:
        frequency = None
    return CpuSnapshot(
        collected_at=datetime.now(UTC),
        source="psutil",
        collector_version=COLLECTOR_VERSION,
        logical_cores=psutil.cpu_count(logical=True) or 0,
        physical_cores=psutil.cpu_count(logical=False),
        max_frequency_mhz=frequency.max if frequency else None,
    )
