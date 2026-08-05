from heimei.inventory.collectors.storage import collect


def test_collect_returns_at_least_one_mount_with_plausible_usage():
    snapshot = collect()

    assert len(snapshot.mounts) >= 1
    for mount in snapshot.mounts:
        assert mount.total_bytes >= 0
        assert 0 <= mount.free_bytes <= mount.total_bytes or mount.total_bytes == 0
        assert 0.0 <= mount.percent <= 100.0
    assert snapshot.source == "psutil"


def test_unreadable_mount_is_skipped_not_fatal(monkeypatch):
    import psutil

    from heimei.inventory.collectors import storage

    class FakePartition:
        mountpoint = "/nonexistent-mount-for-test"

    monkeypatch.setattr(psutil, "disk_partitions", lambda all: [FakePartition()])

    snapshot = storage.collect()

    assert snapshot.mounts == ()
