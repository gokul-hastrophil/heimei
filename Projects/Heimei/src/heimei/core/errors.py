class CoreError(Exception):
    """Base class for all Core Runtime errors."""


class DuplicateManagerError(CoreError):
    def __init__(self, name: str):
        self.name = name
        super().__init__(f"A manager named {name!r} is already registered")


class UnknownDependencyError(CoreError):
    def __init__(self, manager_name: str, dependency_name: str):
        self.manager_name = manager_name
        self.dependency_name = dependency_name
        super().__init__(
            f"Manager {manager_name!r} declares a dependency on {dependency_name!r}, "
            "but no manager with that name is registered"
        )


class DependencyCycleError(CoreError):
    def __init__(self, unresolved: tuple[str, ...]):
        self.unresolved = unresolved
        names = ", ".join(sorted(unresolved))
        super().__init__(
            f"Dependency cycle detected — could not determine a startup order for: {names}"
        )


class RuntimeStateError(CoreError):
    """Raised when a Runtime method is called out of its allowed lifecycle order."""


class ServiceNotRegisteredError(CoreError):
    def __init__(self, service_type: type):
        self.service_type = service_type
        super().__init__(f"No service registered for type {service_type!r}")


class ServiceAlreadyRegisteredError(CoreError):
    def __init__(self, service_type: type):
        self.service_type = service_type
        super().__init__(f"A service is already registered for type {service_type!r}")
