from datetime import UTC, datetime

import psutil
from pydantic import BaseModel

from heimei.inventory.record import InventoryRecord

COLLECTOR_VERSION = "1.0"


class NetworkInterface(BaseModel):
    name: str
    addresses: tuple[str, ...]


class NetworkSnapshot(InventoryRecord):
    interfaces: tuple[NetworkInterface, ...]


def collect() -> NetworkSnapshot:
    interfaces = tuple(
        NetworkInterface(
            name=name,
            addresses=tuple(addr.address for addr in addrs if addr.address),
        )
        for name, addrs in psutil.net_if_addrs().items()
    )
    return NetworkSnapshot(
        collected_at=datetime.now(UTC),
        source="psutil",
        collector_version=COLLECTOR_VERSION,
        interfaces=interfaces,
    )
