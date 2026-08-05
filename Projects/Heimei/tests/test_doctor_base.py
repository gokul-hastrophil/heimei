from datetime import UTC, datetime

import pytest

from heimei.doctor.base import (
    Category,
    CheckNotFoundError,
    DoctorError,
    DuplicateCheckError,
    Finding,
    Severity,
)


def test_finding_requires_a_category():
    finding = Finding(
        check="X",
        category=Category.HARDWARE,
        severity=Severity.OK,
        message="fine",
        evaluated_at=datetime.now(UTC),
    )

    assert finding.category is Category.HARDWARE


def test_finding_detail_is_optional():
    finding = Finding(
        check="X",
        category=Category.STORAGE,
        severity=Severity.OK,
        message="fine",
        evaluated_at=datetime.now(UTC),
    )

    assert finding.detail is None


def test_all_eight_categories_exist():
    names = {category.name for category in Category}
    assert names == {
        "HARDWARE",
        "SOFTWARE",
        "GPU",
        "DOCKER",
        "STORAGE",
        "NETWORK",
        "CONFIGURATION",
        "PERFORMANCE",
    }


def test_severity_is_distinct_from_core_health_state():
    from heimei.core.health import HealthState

    assert Severity is not HealthState
    assert not issubclass(Severity, HealthState)


def test_duplicate_check_error_names_the_check():
    error = DuplicateCheckError("CPU")

    assert error.name == "CPU"
    assert "CPU" in str(error)
    assert isinstance(error, DoctorError)


def test_check_not_found_error_names_the_check():
    error = CheckNotFoundError("Unknown")

    assert error.name == "Unknown"
    assert "Unknown" in str(error)
    assert isinstance(error, DoctorError)


@pytest.mark.parametrize("severity", list(Severity))
def test_every_severity_constructs_a_finding(severity):
    finding = Finding(
        check="X",
        category=Category.HARDWARE,
        severity=severity,
        message="msg",
        evaluated_at=datetime.now(UTC),
    )
    assert finding.severity is severity
