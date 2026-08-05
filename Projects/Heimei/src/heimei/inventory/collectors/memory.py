from datetime import UTC, datetime

import psutil

from heimei.inventory.record import InventoryRecord

COLLECTOR_VERSION = "1.0"


class MemorySnapshot(InventoryRecord):
    total_bytes: int
    available_bytes: int
    percent: float


def collect() -> MemorySnapshot:
    virtual_memory = psutil.virtual_memory()
    return MemorySnapshot(
        collected_at=datetime.now(UTC),
        source="psutil",
        collector_version=COLLECTOR_VERSION,
        total_bytes=virtual_memory.total,
        available_bytes=virtual_memory.available,
        percent=virtual_memory.percent,
    )
