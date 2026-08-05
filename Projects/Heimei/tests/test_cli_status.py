from typer.testing import CliRunner

from heimei.cli.status import app
from heimei.status.models import (
    CpuSummary,
    DockerSummary,
    FindingCounts,
    GpuSummary,
    MachineSummary,
    ManagerSummary,
    MemorySummary,
    NetworkInterfaceSummary,
    NetworkSummary,
    RuntimeSummary,
    StatusSnapshot,
    StorageMountSummary,
    StorageSummary,
)
from heimei.status.service import StatusService

runner = CliRunner()


def _snapshot(*, gpu_available=True, docker_available=True, findings=None, all_started=True):
    if findings is None:
        findings = FindingCounts(ok=6, warning=0, critical=0)
    return StatusSnapshot(
        runtime=RuntimeSummary(
            manager_count=4,
            all_managers_started=all_started,
            managers=(
                ManagerSummary(
                    name="logging", order=0, lifecycle_state="started",
                    health_state="healthy", health_detail=None,
                ),
                ManagerSummary(
                    name="status", order=3, lifecycle_state="started",
                    health_state="healthy", health_detail=None,
                ),
            ),
        ),
        machine=MachineSummary(
            hostname="testhost", system="Linux", release="1.0", architecture="x86_64",
        ),
        cpu=CpuSummary(logical_cores=8, physical_cores=4, max_frequency_mhz=3200.0),
        memory=MemorySummary(
            total_bytes=16_000_000_000, available_bytes=8_000_000_000, percent=50.0
        ),
        storage=StorageSummary(
            mounts=(
                StorageMountSummary(
                    path="/", total_bytes=100_000_000_000, free_bytes=50_000_000_000, percent=50.0
                ),
            ),
        ),
        network=NetworkSummary(interfaces=(NetworkInterfaceSummary(name="eth0", address_count=1),)),
        gpu=GpuSummary(
            available=gpu_available,
            source="pynvml" if gpu_available else "none",
            device_names=("Fake GPU",) if gpu_available else (),
        ),
        docker=DockerSummary(
            available=docker_available,
            version="27.0.0" if docker_available else None,
            source="docker-cli" if docker_available else "none",
        ),
        findings=findings,
    )


class FakeStatusService:
    def __init__(self, snapshot):
        self._snapshot = snapshot

    def snapshot(self):
        return self._snapshot


class FakeServices:
    def __init__(self, status_service):
        self._status_service = status_service

    def get(self, service_type):
        assert service_type is StatusService
        return self._status_service


class FakeApp:
    def __init__(self, status_service):
        self.services = FakeServices(status_service)


def _invoke(snapshot):
    return runner.invoke(app, [], obj=FakeApp(FakeStatusService(snapshot)))


def test_prints_runtime_line_and_exits_zero():
    result = _invoke(_snapshot())

    assert result.exit_code == 0
    assert "Runtime" in result.stdout
    assert "running" in result.stdout
    assert "4 managers" in result.stdout


def test_runtime_state_reports_starting_when_not_all_managers_started():
    result = _invoke(_snapshot(all_started=False))

    assert "starting" in result.stdout


def test_prints_manager_names_and_states_in_a_table():
    result = _invoke(_snapshot())

    assert "logging" in result.stdout
    assert "status" in result.stdout
    assert "started" in result.stdout
    assert "healthy" in result.stdout


def test_prints_machine_summary_fields():
    result = _invoke(_snapshot())

    assert "testhost" in result.stdout
    assert "8 logical cores" in result.stdout
    assert "50.0% used" in result.stdout


def test_prints_doctor_finding_counts():
    result = _invoke(_snapshot(findings=FindingCounts(ok=4, warning=1, critical=1)))

    assert "4 ok" in result.stdout
    assert "1 warning" in result.stdout
    assert "1 critical" in result.stdout


def test_exits_zero_even_when_doctor_findings_include_critical():
    """Status reports, it never judges — unlike `heimei doctor`, a
    critical finding count must not change the exit code.
    """
    result = _invoke(_snapshot(findings=FindingCounts(ok=0, warning=0, critical=3)))

    assert result.exit_code == 0


def test_gpu_unavailable_prints_not_available_without_crashing():
    result = _invoke(_snapshot(gpu_available=False))

    assert result.exit_code == 0
    assert "not available" in result.stdout


def test_docker_unavailable_prints_not_available_without_crashing():
    result = _invoke(_snapshot(docker_available=False))

    assert result.exit_code == 0
    assert "not available" in result.stdout
