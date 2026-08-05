import subprocess
import sys
import types

import pytest

from heimei.inventory.collectors import gpu


class FakePynvmlModule(types.ModuleType):
    def __init__(self, devices, fail_init=False, fail_count=False, fail_shutdown=False):
        super().__init__("pynvml")
        self._devices = devices
        self._fail_init = fail_init
        self._fail_count = fail_count
        self._fail_shutdown = fail_shutdown
        self.shutdown_called = False

    def nvmlInit(self):
        if self._fail_init:
            raise RuntimeError("driver not loaded")

    def nvmlDeviceGetCount(self):
        if self._fail_count:
            raise RuntimeError("boom")
        return len(self._devices)

    def nvmlDeviceGetHandleByIndex(self, index):
        return index

    def nvmlDeviceGetName(self, handle):
        return self._devices[handle]["name"]

    def nvmlDeviceGetMemoryInfo(self, handle):
        return types.SimpleNamespace(total=self._devices[handle]["memory"])

    def nvmlShutdown(self):
        self.shutdown_called = True
        if self._fail_shutdown:
            raise RuntimeError("uninitialized")


@pytest.fixture
def no_pynvml(monkeypatch):
    monkeypatch.setitem(sys.modules, "pynvml", None)


def install_fake_pynvml(monkeypatch, **kwargs):
    fake = FakePynvmlModule(**kwargs)
    monkeypatch.setitem(sys.modules, "pynvml", fake)
    return fake


def only_on_path(monkeypatch, *names):
    monkeypatch.setattr(
        gpu.shutil, "which", lambda name: f"/usr/bin/{name}" if name in names else None
    )


def fake_stdout(monkeypatch, stdout):
    monkeypatch.setattr(
        gpu.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout=stdout, stderr=""),
    )


def test_pynvml_with_devices_wins_immediately(monkeypatch):
    install_fake_pynvml(monkeypatch, devices=[{"name": "RTX 3050", "memory": 4_294_967_296}])
    only_on_path(monkeypatch)  # sabotage lower layers so a false-positive fallthrough is caught

    snapshot = gpu.collect()

    assert snapshot.available is True
    assert snapshot.source == "pynvml"
    assert snapshot.devices == (gpu.GpuDevice(name="RTX 3050", memory_total_bytes=4_294_967_296),)


def test_pynvml_decodes_bytes_device_name(monkeypatch):
    fake = install_fake_pynvml(monkeypatch, devices=[{"name": b"RTX 3050", "memory": 100}])
    only_on_path(monkeypatch)

    snapshot = gpu.collect()

    assert snapshot.devices[0].name == "RTX 3050"
    assert fake.shutdown_called is True


def test_pynvml_not_installed_falls_through_to_nvidia_smi(monkeypatch, no_pynvml):
    only_on_path(monkeypatch, "nvidia-smi")
    fake_stdout(monkeypatch, "RTX 3050, 4096\n")

    snapshot = gpu.collect()

    assert snapshot.available is True
    assert snapshot.source == "nvidia-smi"
    assert snapshot.devices[0].name == "RTX 3050"
    assert snapshot.devices[0].memory_total_bytes == 4096 * 1024 * 1024


def test_nvidia_smi_unparsable_memory_keeps_device(monkeypatch, no_pynvml):
    only_on_path(monkeypatch, "nvidia-smi")
    fake_stdout(monkeypatch, "RTX 3050, [N/A]\n")

    snapshot = gpu.collect()

    assert snapshot.available is True
    assert snapshot.devices[0].name == "RTX 3050"
    assert snapshot.devices[0].memory_total_bytes is None


def test_pynvml_shutdown_failure_does_not_lose_the_collected_devices(monkeypatch):
    fake = install_fake_pynvml(
        monkeypatch,
        devices=[{"name": "RTX 3050", "memory": 4_294_967_296}],
        fail_shutdown=True,
    )
    only_on_path(monkeypatch)

    snapshot = gpu.collect()

    assert snapshot.available is True
    assert snapshot.source == "pynvml"
    assert snapshot.devices[0].name == "RTX 3050"
    assert fake.shutdown_called is True


def test_pynvml_init_failure_falls_through_to_nvidia_smi(monkeypatch):
    install_fake_pynvml(monkeypatch, devices=[], fail_init=True)
    only_on_path(monkeypatch, "nvidia-smi")
    fake_stdout(monkeypatch, "RTX 3050, 4096\n")

    snapshot = gpu.collect()

    assert snapshot.source == "nvidia-smi"


def test_pynvml_zero_devices_still_falls_through(monkeypatch):
    """pynvml only sees NVIDIA hardware; an empty result must not stop
    the chain, or a non-NVIDIA GPU visible only to lspci would be missed.
    """
    install_fake_pynvml(monkeypatch, devices=[])
    only_on_path(monkeypatch, "lspci")
    fake_stdout(monkeypatch, "00:02.0 VGA compatible controller: Intel Corporation UHD Graphics\n")

    snapshot = gpu.collect()

    assert snapshot.available is True
    assert snapshot.source == "lspci"
    assert "Intel" in snapshot.devices[0].name


def test_nvidia_smi_not_on_path_falls_through_to_lspci(monkeypatch, no_pynvml):
    only_on_path(monkeypatch, "lspci")
    fake_stdout(monkeypatch, "00:02.0 3D controller: AMD Radeon\n")

    snapshot = gpu.collect()

    assert snapshot.source == "lspci"
    assert "AMD Radeon" in snapshot.devices[0].name


def test_nvidia_smi_command_failure_falls_through_to_lspci(monkeypatch, no_pynvml):
    def fake_run(cmd, **kwargs):
        if cmd[0] == "nvidia-smi":
            raise subprocess.CalledProcessError(1, cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    only_on_path(monkeypatch, "nvidia-smi", "lspci")
    monkeypatch.setattr(gpu.subprocess, "run", fake_run)

    snapshot = gpu.collect()

    assert snapshot.source == "lspci"
    assert snapshot.available is False  # lspci ran but found nothing in this fake output


def test_all_layers_unavailable_reports_available_false(monkeypatch, no_pynvml):
    only_on_path(monkeypatch)

    snapshot = gpu.collect()

    assert snapshot.available is False
    assert snapshot.devices == ()
    assert snapshot.source == "none"


def test_lspci_runs_but_finds_nothing_reports_that_source(monkeypatch, no_pynvml):
    only_on_path(monkeypatch, "lspci")
    fake_stdout(monkeypatch, "00:1f.0 ISA bridge: Intel\n")

    snapshot = gpu.collect()

    assert snapshot.available is False
    assert snapshot.source == "lspci"


def test_collect_never_raises_on_subprocess_timeout(monkeypatch, no_pynvml):
    def fake_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, 5)

    only_on_path(monkeypatch, "nvidia-smi", "lspci")
    monkeypatch.setattr(gpu.subprocess, "run", fake_run)

    snapshot = gpu.collect()

    assert snapshot.available is False
