import platform
import socket
from datetime import UTC, datetime

from heimei.inventory.record import InventoryRecord

COLLECTOR_VERSION = "1.0"


class MachineSnapshot(InventoryRecord):
    """Live-discovered machine identity. See ADR-0013, section 7.

    Deliberately unrelated to ``heimei.config``'s ``MachineManifest`` —
    that is static, user-curated; this is discovered right now and may
    legitimately disagree with it.
    """

    hostname: str
    system: str
    release: str
    architecture: str


def collect() -> MachineSnapshot:
    return MachineSnapshot(
        collected_at=datetime.now(UTC),
        source="platform",
        collector_version=COLLECTOR_VERSION,
        hostname=socket.gethostname(),
        system=platform.system(),
        release=platform.release(),
        architecture=platform.machine(),
    )
