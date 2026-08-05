from typing import TypeVar, cast

from heimei.core.errors import ServiceAlreadyRegisteredError, ServiceNotRegisteredError

T = TypeVar("T")


class ServiceContainer:
    """Owns shared service instances, keyed by type.

    Exactly three operations, permanently: ``register``, ``get``, ``has``.
    No scoping or lifetimes, no factories or lazy construction, no
    auto-wiring, no child containers — see ADR-0011, section 3. Every
    registration is an already-constructed instance handed in explicitly
    by whoever owns it.
    """

    def __init__(self) -> None:
        self._services: dict[type, object] = {}

    def register(self, service_type: type[T], instance: T) -> None:
        if service_type in self._services:
            raise ServiceAlreadyRegisteredError(service_type)
        self._services[service_type] = instance

    def get(self, service_type: type[T]) -> T:
        try:
            instance = self._services[service_type]
        except KeyError:
            raise ServiceNotRegisteredError(service_type) from None
        return cast(T, instance)

    def has(self, service_type: type[T]) -> bool:
        return service_type in self._services
