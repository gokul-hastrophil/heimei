from dataclasses import dataclass

from heimei.core.container import ServiceContainer


@dataclass(frozen=True)
class RuntimeContext:
    """Passed to Manager.initialize() — see ADR-0011, section 5.

    Carries exactly one thing. A manager resolves every dependency
    through ``context.services``; no other attribute is ever added here
    for a specific service.
    """

    services: ServiceContainer
