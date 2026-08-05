import shutil
import subprocess
from datetime import UTC, datetime

from heimei.inventory.record import InventoryRecord

COLLECTOR_VERSION = "1.0"


class DockerSnapshot(InventoryRecord):
    """See ADR-0013, section 5. ``available=False`` covers "Docker not
    installed" and "installed but the daemon isn't running" alike —
    both make Docker equally unusable right now, and this collector
    never raises for either.
    """

    available: bool
    version: str | None = None


def _version_via_engine_api() -> str | None:
    try:
        import docker  # type: ignore[import-untyped]
    except ImportError:
        return None
    try:
        client = docker.from_env()
    except Exception:
        return None
    try:
        return client.version().get("Version")
    except Exception:
        return None
    finally:
        client.close()


def _version_via_cli() -> str | None:
    if shutil.which("docker") is None:
        return None
    try:
        result = subprocess.run(
            ["docker", "version", "--format", "{{.Server.Version}}"],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    version = result.stdout.strip()
    return version or None


def collect() -> DockerSnapshot:
    for source, mechanism in (
        ("docker-engine-api", _version_via_engine_api),
        ("docker-cli", _version_via_cli),
    ):
        version = mechanism()
        if version:
            return DockerSnapshot(
                collected_at=datetime.now(UTC),
                source=source,
                collector_version=COLLECTOR_VERSION,
                available=True,
                version=version,
            )

    return DockerSnapshot(
        collected_at=datetime.now(UTC),
        source="none",
        collector_version=COLLECTOR_VERSION,
        available=False,
        version=None,
    )
