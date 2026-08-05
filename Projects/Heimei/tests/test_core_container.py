import pytest

from heimei.core.container import ServiceContainer
from heimei.core.errors import ServiceAlreadyRegisteredError, ServiceNotRegisteredError


class Alpha:
    pass


class Beta:
    pass


def test_register_then_get_returns_same_instance():
    container = ServiceContainer()
    instance = Alpha()

    container.register(Alpha, instance)

    assert container.get(Alpha) is instance


def test_has_is_false_before_registration_and_true_after():
    container = ServiceContainer()

    assert container.has(Alpha) is False

    container.register(Alpha, Alpha())

    assert container.has(Alpha) is True


def test_get_missing_service_raises_clear_error():
    container = ServiceContainer()

    with pytest.raises(ServiceNotRegisteredError) as exc_info:
        container.get(Alpha)

    assert "Alpha" in str(exc_info.value)


def test_register_same_type_twice_raises():
    container = ServiceContainer()
    container.register(Alpha, Alpha())

    with pytest.raises(ServiceAlreadyRegisteredError):
        container.register(Alpha, Alpha())


def test_different_types_are_independent():
    container = ServiceContainer()
    a, b = Alpha(), Beta()

    container.register(Alpha, a)
    container.register(Beta, b)

    assert container.get(Alpha) is a
    assert container.get(Beta) is b
    assert container.has(Alpha) is True
    assert container.has(Beta) is True
