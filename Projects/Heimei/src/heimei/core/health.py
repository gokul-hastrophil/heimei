from dataclasses import dataclass
from enum import Enum


class HealthState(Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


@dataclass(frozen=True)
class HealthStatus:
    """The shape every Manager.health() returns — see ADR-0011, section 4.

    Only the interface is frozen. What counts as DEGRADED vs. UNHEALTHY
    for a given manager, and how ``detail`` is worded, is left entirely
    to that manager.
    """

    state: HealthState
    detail: str | None = None
