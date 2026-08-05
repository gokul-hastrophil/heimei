from heimei.inventory.collectors.cpu import collect


def test_collect_returns_plausible_cpu_facts():
    snapshot = collect()

    assert snapshot.logical_cores >= 1
    assert snapshot.physical_cores is None or snapshot.physical_cores >= 1
    assert snapshot.source == "psutil"
    assert snapshot.collector_version == "1.0"
