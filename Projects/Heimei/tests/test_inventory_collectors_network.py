from heimei.inventory.collectors.network import collect


def test_collect_returns_at_least_one_interface():
    snapshot = collect()

    assert len(snapshot.interfaces) >= 1
    for interface in snapshot.interfaces:
        assert interface.name
        assert all(isinstance(addr, str) for addr in interface.addresses)
    assert snapshot.source == "psutil"
