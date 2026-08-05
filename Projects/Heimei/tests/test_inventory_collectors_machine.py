import socket

from heimei.inventory.collectors.machine import collect


def test_collect_returns_real_hostname_and_platform_facts():
    snapshot = collect()

    assert snapshot.hostname == socket.gethostname()
    assert snapshot.system  # non-empty
    assert snapshot.release
    assert snapshot.architecture
    assert snapshot.source == "platform"
    assert snapshot.collector_version == "1.0"
