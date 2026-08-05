import pytest

from heimei.inventory.service import InventoryService


@pytest.fixture
def service():
    return InventoryService()


def _stub_collector(monkeypatch, method_name):
    """Replace a collector with a side-effect-free stub. The service only
    ever checks the cached value for identity/None-ness, so a fresh
    sentinel per call is enough to test caching without running any real
    (and possibly slow, host-dependent) collection logic.
    """
    import heimei.inventory.collectors as collectors_pkg

    collector = getattr(collectors_pkg, method_name)
    calls = []

    def stub():
        calls.append(1)
        return object()

    monkeypatch.setattr(collector, "collect", stub)
    return calls


@pytest.mark.parametrize("method_name", ["machine", "cpu", "python"])
def test_non_volatile_methods_cache_after_first_call(service, monkeypatch, method_name):
    calls = _stub_collector(monkeypatch, method_name)

    first = getattr(service, method_name)()
    second = getattr(service, method_name)()

    assert first is second
    assert len(calls) == 1


@pytest.mark.parametrize("method_name", ["machine", "cpu", "python"])
def test_non_volatile_methods_accept_no_refresh_kwarg(service, method_name):
    with pytest.raises(TypeError):
        getattr(service, method_name)(refresh=True)


@pytest.mark.parametrize("method_name", ["memory", "storage", "network", "gpu", "docker"])
def test_volatile_methods_cache_by_default(service, monkeypatch, method_name):
    calls = _stub_collector(monkeypatch, method_name)

    first = getattr(service, method_name)()
    second = getattr(service, method_name)()

    assert first is second
    assert len(calls) == 1


@pytest.mark.parametrize("method_name", ["memory", "storage", "network", "gpu", "docker"])
def test_volatile_methods_refresh_bypasses_the_cache(service, monkeypatch, method_name):
    calls = _stub_collector(monkeypatch, method_name)

    getattr(service, method_name)()
    getattr(service, method_name)(refresh=True)

    assert len(calls) == 2


def test_service_has_exactly_eight_public_snapshot_methods():
    public_methods = {
        name
        for name in dir(InventoryService)
        if not name.startswith("_") and callable(getattr(InventoryService, name))
    }

    assert public_methods == {
        "machine",
        "cpu",
        "python",
        "memory",
        "storage",
        "network",
        "gpu",
        "docker",
    }
