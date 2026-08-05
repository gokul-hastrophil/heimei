from datetime import UTC, datetime

import pytest

from heimei.doctor.base import Category, CheckNotFoundError, DuplicateCheckError, Finding, Severity
from heimei.doctor.service import DoctorService


class FakeInventory:
    pass


class RecordingCheck:
    """Records every InventoryService instance it was called with, so
    tests can assert DoctorService hands out the same one every time.
    """

    def __init__(self, name, category=Category.HARDWARE, severity=Severity.OK):
        self.name = name
        self.category = category
        self._severity = severity
        self.received = []

    def run(self, inventory):
        self.received.append(inventory)
        return (
            Finding(
                check=self.name,
                category=self.category,
                severity=self._severity,
                message="ok",
                evaluated_at=datetime.now(UTC),
            ),
        )


class RaisingCheck:
    name = "Broken"
    category = Category.HARDWARE

    def run(self, inventory):
        raise RuntimeError("kaboom")


def test_register_then_run_produces_that_checks_finding():
    service = DoctorService(FakeInventory())
    check = RecordingCheck("CPU")
    service.register(check)

    (finding,) = service.run()

    assert finding.check == "CPU"


def test_register_duplicate_name_raises():
    service = DoctorService(FakeInventory())
    service.register(RecordingCheck("CPU"))

    with pytest.raises(DuplicateCheckError):
        service.register(RecordingCheck("CPU"))


def test_resolves_inventory_service_exactly_once_and_reuses_it():
    inventory = FakeInventory()
    service = DoctorService(inventory)
    a, b = RecordingCheck("A"), RecordingCheck("B")
    service.register(a)
    service.register(b)

    service.run()

    assert a.received == [inventory]
    assert b.received == [inventory]


def test_run_with_no_filters_runs_every_check():
    service = DoctorService(FakeInventory())
    service.register(RecordingCheck("A"))
    service.register(RecordingCheck("B"))

    findings = service.run()

    assert {f.check for f in findings} == {"A", "B"}


def test_run_by_category_only_runs_matching_checks():
    service = DoctorService(FakeInventory())
    service.register(RecordingCheck("A", category=Category.HARDWARE))
    service.register(RecordingCheck("B", category=Category.NETWORK))

    findings = service.run(category=Category.NETWORK)

    assert {f.check for f in findings} == {"B"}


def test_run_by_check_name_only_runs_that_check():
    service = DoctorService(FakeInventory())
    service.register(RecordingCheck("A"))
    service.register(RecordingCheck("B"))

    findings = service.run(check="A")

    assert {f.check for f in findings} == {"A"}


def test_run_by_unknown_check_name_raises():
    service = DoctorService(FakeInventory())
    service.register(RecordingCheck("A"))

    with pytest.raises(CheckNotFoundError):
        service.run(check="Unknown")


def test_check_name_takes_precedence_over_category_when_both_given():
    service = DoctorService(FakeInventory())
    service.register(RecordingCheck("A", category=Category.HARDWARE))
    service.register(RecordingCheck("B", category=Category.NETWORK))

    findings = service.run(check="A", category=Category.NETWORK)

    assert {f.check for f in findings} == {"A"}


def test_a_raising_check_becomes_a_critical_finding_not_an_exception():
    service = DoctorService(FakeInventory())
    service.register(RaisingCheck())

    (finding,) = service.run()

    assert finding.severity is Severity.CRITICAL
    assert finding.check == "Broken"
    assert "kaboom" in finding.message


def test_a_raising_check_does_not_prevent_other_checks_from_running():
    service = DoctorService(FakeInventory())
    service.register(RaisingCheck())
    service.register(RecordingCheck("Healthy"))

    findings = service.run()

    checks_that_ran = {f.check for f in findings}
    assert checks_that_ran == {"Broken", "Healthy"}
    severities = {f.check: f.severity for f in findings}
    assert severities["Broken"] is Severity.CRITICAL
    assert severities["Healthy"] is Severity.OK


def test_run_never_interprets_or_aggregates_findings():
    """The engine has no business logic — it returns exactly what each
    check produced, concatenated, in registration order.
    """
    service = DoctorService(FakeInventory())
    service.register(RecordingCheck("A", severity=Severity.CRITICAL))
    service.register(RecordingCheck("B", severity=Severity.OK))

    findings = service.run()

    assert [f.check for f in findings] == ["A", "B"]
    assert [f.severity for f in findings] == [Severity.CRITICAL, Severity.OK]
