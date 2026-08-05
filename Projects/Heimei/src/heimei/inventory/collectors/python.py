import platform
import sys
from datetime import UTC, datetime

from heimei.inventory.record import InventoryRecord

COLLECTOR_VERSION = "1.0"


class PythonSnapshot(InventoryRecord):
    """The running interpreter's identity. No ``refresh`` — this cannot
    change within a process's lifetime.
    """

    version: str
    executable: str
    implementation: str


def collect() -> PythonSnapshot:
    return PythonSnapshot(
        collected_at=datetime.now(UTC),
        source="sys",
        collector_version=COLLECTOR_VERSION,
        version=platform.python_version(),
        executable=sys.executable,
        implementation=platform.python_implementation(),
    )
