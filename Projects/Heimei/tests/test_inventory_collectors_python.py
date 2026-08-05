import sys

from heimei.inventory.collectors.python import collect


def test_collect_returns_the_running_interpreter():
    snapshot = collect()

    assert snapshot.executable == sys.executable
    assert snapshot.implementation
    assert snapshot.version
    assert snapshot.source == "sys"
