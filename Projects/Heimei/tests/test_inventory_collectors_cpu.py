from heimei.inventory.collectors import cpu
from heimei.inventory.collectors.cpu import collect


def test_collect_returns_plausible_cpu_facts():
    snapshot = collect()

    assert snapshot.logical_cores >= 1
    assert snapshot.physical_cores is None or snapshot.physical_cores >= 1
    assert snapshot.source == "psutil"
    assert snapshot.collector_version == "1.0"


def test_collect_survives_cpu_freq_not_implemented(monkeypatch):
    def fake_cpu_freq():
        raise NotImplementedError

    monkeypatch.setattr(cpu.psutil, "cpu_freq", fake_cpu_freq)

    snapshot = collect()

    assert snapshot.max_frequency_mhz is None
