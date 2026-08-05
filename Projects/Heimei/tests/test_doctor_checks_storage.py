from datetime import UTC, datetime

from heimei.doctor.base import Category, Severity
from heimei.doctor.checks.storage import StorageCheck
from heimei.inventory.collectors.storage import StorageMount, StorageSnapshot


class FakeInventory:
    def __init__(self, mounts):
        self.refresh_requested = None
        self._mounts = mounts

    def storage(self, *, refresh=False):
        self.refresh_requested = refresh
        return StorageSnapshot(
            collected_at=datetime.now(UTC),
            source="fake",
            collector_version="1.0",
            mounts=tuple(self._mounts),
        )


def _mount(path, percent):
    total = 1_000_000_000
    return StorageMount(
        path=path, total_bytes=total, free_bytes=int(total * (1 - percent / 100)), percent=percent
    )


def test_identity():
    check = StorageCheck()
    assert check.name == "Storage"
    assert check.category is Category.STORAGE


def test_requests_a_fresh_reading():
    check = StorageCheck()
    inventory = FakeInventory([_mount("/", 10.0)])

    check.run(inventory)

    assert inventory.refresh_requested is True


def test_plenty_of_free_space_is_ok():
    check = StorageCheck()

    (finding,) = check.run(FakeInventory([_mount("/", 20.0)]))

    assert finding.severity is Severity.OK


def test_low_free_space_is_warning():
    check = StorageCheck()

    (finding,) = check.run(FakeInventory([_mount("/", 90.0)]))

    assert finding.severity is Severity.WARNING
    assert "/" in finding.message
    assert "10.0" in finding.message


def test_critically_low_free_space_is_critical():
    check = StorageCheck()

    (finding,) = check.run(FakeInventory([_mount("/", 97.0)]))

    assert finding.severity is Severity.CRITICAL
    assert "/" in finding.message


def test_no_mounts_at_all_is_ok():
    check = StorageCheck()

    (finding,) = check.run(FakeInventory([]))

    assert finding.severity is Severity.OK
    assert "No storage mounts" in finding.message


def test_snap_mounts_are_excluded_even_at_100_percent_used():
    """Regression test: snap packages mount as fixed-size, read-only
    squashfs images that always report ~0% free by design — flagging
    them as critical disk usage is pure noise, found via manual testing.
    """
    check = StorageCheck()

    (finding,) = check.run(FakeInventory([_mount("/snap/firefox/8107", 100.0)]))

    assert finding.severity is Severity.OK
    assert "No storage mounts" in finding.message


def test_snap_mounts_excluded_but_real_mounts_still_evaluated():
    check = StorageCheck()

    findings = check.run(
        FakeInventory([_mount("/snap/core22/2411", 100.0), _mount("/", 97.0)])
    )

    assert len(findings) == 1
    assert findings[0].severity is Severity.CRITICAL
    assert findings[0].detail["path"] == "/"


def test_multiple_real_mounts_each_produce_their_own_finding():
    check = StorageCheck()

    findings = check.run(FakeInventory([_mount("/", 10.0), _mount("/home", 97.0)]))

    assert len(findings) == 2
    by_path = {f.detail["path"]: f for f in findings}
    assert by_path["/"].severity is Severity.OK
    assert by_path["/home"].severity is Severity.CRITICAL
