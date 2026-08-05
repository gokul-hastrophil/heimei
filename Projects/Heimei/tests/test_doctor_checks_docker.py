from datetime import UTC, datetime

from heimei.doctor.base import Category, Severity
from heimei.doctor.checks.docker import DockerCheck
from heimei.inventory.collectors.docker import DockerSnapshot


class FakeInventory:
    def __init__(self, available, version=None):
        self.refresh_requested = None
        self._snapshot = DockerSnapshot(
            collected_at=datetime.now(UTC),
            source="fake",
            collector_version="1.0",
            available=available,
            version=version,
        )

    def docker(self, *, refresh=False):
        self.refresh_requested = refresh
        return self._snapshot


def test_identity():
    check = DockerCheck()
    assert check.name == "Docker"
    assert check.category is Category.DOCKER


def test_requests_a_fresh_reading():
    check = DockerCheck()
    inventory = FakeInventory(available=False)

    check.run(inventory)

    assert inventory.refresh_requested is True


def test_running_is_ok():
    check = DockerCheck()

    (finding,) = check.run(FakeInventory(available=True, version="27.0.0"))

    assert finding.severity is Severity.OK
    assert "27.0.0" in finding.message


def test_not_detected_is_ok_not_a_problem():
    check = DockerCheck()

    (finding,) = check.run(FakeInventory(available=False))

    assert finding.severity is Severity.OK
    assert "not detected" in finding.message.lower()
