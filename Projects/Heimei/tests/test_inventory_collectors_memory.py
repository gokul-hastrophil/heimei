from heimei.inventory.collectors.memory import collect


def test_collect_returns_plausible_memory_facts():
    snapshot = collect()

    assert snapshot.total_bytes > 0
    assert 0 <= snapshot.available_bytes <= snapshot.total_bytes
    assert 0.0 <= snapshot.percent <= 100.0
    assert snapshot.source == "psutil"
