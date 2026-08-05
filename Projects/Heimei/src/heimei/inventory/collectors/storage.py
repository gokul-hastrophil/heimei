from datetime import UTC, datetime

import psutil
from pydantic import BaseModel

from heimei.inventory.record import InventoryRecord

COLLECTOR_VERSION = "1.0"


class StorageMount(BaseModel):
    path: str
    total_bytes: int
    free_bytes: int
    percent: float


class StorageSnapshot(InventoryRecord):
    mounts: tuple[StorageMount, ...]


def collect() -> StorageSnapshot:
    mounts = []
    for partition in psutil.disk_partitions(all=False):
        try:
            usage = psutil.disk_usage(partition.mountpoint)
        except OSError:
            # Some mountpoints (e.g. removable media with no medium) are
            # legitimately unreadable; skip rather than fail the whole snapshot.
            continue
        mounts.append(
            StorageMount(
                path=partition.mountpoint,
                total_bytes=usage.total,
                free_bytes=usage.free,
                percent=usage.percent,
            )
        )
    return StorageSnapshot(
        collected_at=datetime.now(UTC),
        source="psutil",
        collector_version=COLLECTOR_VERSION,
        mounts=tuple(mounts),
    )
