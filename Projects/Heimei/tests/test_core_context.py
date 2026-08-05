import dataclasses

import pytest

from heimei.core.container import ServiceContainer
from heimei.core.context import RuntimeContext


def test_context_carries_the_container():
    container = ServiceContainer()

    context = RuntimeContext(services=container)

    assert context.services is container


def test_context_is_frozen():
    context = RuntimeContext(services=ServiceContainer())

    with pytest.raises(dataclasses.FrozenInstanceError):
        context.services = ServiceContainer()
