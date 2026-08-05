from typing import Protocol

from heimei.core.context import RuntimeContext
from heimei.core.health import HealthStatus


class Manager(Protocol):
    """The lifecycle every Core Runtime manager implements — ADR-0011, section 1.

    ``initialize`` does wiring only: resolve dependencies and register
    whatever this manager exposes, via ``context.services``. ``startup``
    activates, with no arguments, only after every manager has been
    initialized. ``health`` may be called at any time after
    ``initialize``. ``shutdown`` reverses ``startup`` — there is no
    separate "deinitialize" step.
    """

    name: str
    dependencies: tuple[str, ...]

    def initialize(self, context: RuntimeContext) -> None: ...
    def startup(self) -> None: ...
    def health(self) -> HealthStatus: ...
    def shutdown(self) -> None: ...
