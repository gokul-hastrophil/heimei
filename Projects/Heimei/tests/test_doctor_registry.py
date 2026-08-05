import pytest

from heimei.doctor.base import Category, CheckNotFoundError, DuplicateCheckError
from heimei.doctor.registry import CheckRegistry


class FakeCheck:
    """CheckRegistry is pure storage — it never calls run(), so this
    double doesn't need a real implementation of it.
    """

    def __init__(self, name, category):
        self.name = name
        self.category = category

    def run(self, inventory):
        raise NotImplementedError


@pytest.fixture
def registry():
    return CheckRegistry()


def test_register_then_get_returns_the_same_check(registry):
    check = FakeCheck("CPU", Category.HARDWARE)
    registry.register(check)

    assert registry.get("CPU") is check


def test_register_duplicate_name_raises(registry):
    registry.register(FakeCheck("CPU", Category.HARDWARE))

    with pytest.raises(DuplicateCheckError):
        registry.register(FakeCheck("CPU", Category.PERFORMANCE))


def test_get_missing_check_raises(registry):
    with pytest.raises(CheckNotFoundError):
        registry.get("Unknown")


def test_all_returns_every_registered_check_in_registration_order(registry):
    a = FakeCheck("A", Category.HARDWARE)
    b = FakeCheck("B", Category.NETWORK)
    registry.register(a)
    registry.register(b)

    assert registry.all() == (a, b)


def test_by_category_filters_correctly(registry):
    cpu = FakeCheck("CPU", Category.HARDWARE)
    memory = FakeCheck("Memory", Category.PERFORMANCE)
    gpu = FakeCheck("GPU", Category.HARDWARE)
    registry.register(cpu)
    registry.register(memory)
    registry.register(gpu)

    assert set(registry.by_category(Category.HARDWARE)) == {cpu, gpu}
    assert registry.by_category(Category.NETWORK) == ()


def test_empty_registry_returns_empty_tuples(registry):
    assert registry.all() == ()
    assert registry.by_category(Category.HARDWARE) == ()
