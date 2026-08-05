import dataclasses

import pytest

from heimei.core.health import HealthState, HealthStatus


def test_health_status_holds_state_and_optional_detail():
    status = HealthStatus(state=HealthState.HEALTHY)

    assert status.state is HealthState.HEALTHY
    assert status.detail is None


def test_health_status_detail_is_optional_but_settable():
    status = HealthStatus(state=HealthState.DEGRADED, detail="cache miss rate high")

    assert status.detail == "cache miss rate high"


def test_health_status_is_frozen():
    status = HealthStatus(state=HealthState.UNHEALTHY)

    with pytest.raises(dataclasses.FrozenInstanceError):
        status.state = HealthState.HEALTHY
