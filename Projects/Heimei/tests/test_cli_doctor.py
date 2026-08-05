from datetime import UTC, datetime

from typer.testing import CliRunner

from heimei.cli.doctor import app
from heimei.doctor.base import Category, Finding, Severity
from heimei.doctor.service import DoctorService

runner = CliRunner()


class FakeCheck:
    def __init__(self, name, findings):
        self.name = name
        self.category = Category.HARDWARE
        self._findings = findings

    def run(self, inventory):
        return tuple(self._findings)


def _finding(check, severity, message):
    return Finding(
        check=check, category=Category.HARDWARE, severity=severity, message=message,
        evaluated_at=datetime.now(UTC),
    )


class FakeServices:
    def __init__(self, doctor_service):
        self._doctor_service = doctor_service

    def get(self, service_type):
        assert service_type is DoctorService
        return self._doctor_service


class FakeApp:
    def __init__(self, doctor_service):
        self.services = FakeServices(doctor_service)


def _invoke(doctor_service):
    return runner.invoke(app, [], obj=FakeApp(doctor_service))


def test_all_ok_checks_print_one_checkmark_line_each():
    service = DoctorService(inventory=None)
    service.register(FakeCheck("CPU", [_finding("CPU", Severity.OK, "fine")]))
    service.register(FakeCheck("Memory", [_finding("Memory", Severity.OK, "fine")]))

    result = _invoke(service)

    assert result.exit_code == 0
    assert "✔ CPU" in result.stdout
    assert "✔ Memory" in result.stdout


def test_warning_finding_prints_its_message_not_a_checkmark():
    service = DoctorService(inventory=None)
    service.register(
        FakeCheck("Storage", [_finding("Storage", Severity.WARNING, "Disk usage high")])
    )

    result = _invoke(service)

    assert result.exit_code == 0
    assert "⚠ Disk usage high" in result.stdout
    assert "✔ Storage" not in result.stdout


def test_critical_finding_prints_its_message_and_exits_nonzero():
    service = DoctorService(inventory=None)
    service.register(
        FakeCheck("GPU", [_finding("GPU", Severity.CRITICAL, "NVIDIA driver missing")])
    )

    result = _invoke(service)

    assert result.exit_code == 1
    assert "✖ NVIDIA driver missing" in result.stdout


def test_mixed_severities_across_checks_matches_documented_example():
    service = DoctorService(inventory=None)
    service.register(FakeCheck("CPU", [_finding("CPU", Severity.OK, "fine")]))
    service.register(FakeCheck("Memory", [_finding("Memory", Severity.OK, "fine")]))
    service.register(FakeCheck("Docker", [_finding("Docker", Severity.OK, "fine")]))
    service.register(
        FakeCheck("Storage", [_finding("Storage", Severity.WARNING, "Disk usage high")])
    )
    service.register(
        FakeCheck("GPU", [_finding("GPU", Severity.CRITICAL, "NVIDIA driver missing")])
    )

    result = _invoke(service)

    lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert lines == [
        "✔ CPU",
        "✔ Memory",
        "✔ Docker",
        "⚠ Disk usage high",
        "✖ NVIDIA driver missing",
    ]
    assert result.exit_code == 1


def test_check_with_mixed_findings_shows_only_the_problems_not_a_checkmark():
    service = DoctorService(inventory=None)
    service.register(
        FakeCheck(
            "Storage",
            [
                _finding("Storage", Severity.OK, "/: 50% free"),
                _finding("Storage", Severity.WARNING, "Disk usage high"),
            ],
        )
    )

    result = _invoke(service)

    assert "✔ Storage" not in result.stdout
    assert "⚠ Disk usage high" in result.stdout


def test_no_checks_registered_prints_nothing_and_exits_zero():
    service = DoctorService(inventory=None)

    result = _invoke(service)

    assert result.exit_code == 0
    assert result.stdout.strip() == ""


def test_warning_only_exits_zero():
    service = DoctorService(inventory=None)
    service.register(
        FakeCheck("Storage", [_finding("Storage", Severity.WARNING, "Disk usage high")])
    )

    result = _invoke(service)

    assert result.exit_code == 0
