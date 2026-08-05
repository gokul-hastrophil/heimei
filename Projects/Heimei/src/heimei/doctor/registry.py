from heimei.doctor.base import Category, CheckNotFoundError, DuplicateCheckError, HealthCheck


class CheckRegistry:
    """Pure storage for registered HealthChecks. No orchestration logic
    — running checks and collecting Findings is DoctorService's job.
    See ADR-0014.
    """

    def __init__(self) -> None:
        self._checks: dict[str, HealthCheck] = {}

    def register(self, check: HealthCheck) -> None:
        if check.name in self._checks:
            raise DuplicateCheckError(check.name)
        self._checks[check.name] = check

    def get(self, name: str) -> HealthCheck:
        try:
            return self._checks[name]
        except KeyError:
            raise CheckNotFoundError(name) from None

    def all(self) -> tuple[HealthCheck, ...]:
        return tuple(self._checks.values())

    def by_category(self, category: Category) -> tuple[HealthCheck, ...]:
        return tuple(check for check in self._checks.values() if check.category is category)
