"""Sink configuration for the Logging Manager.

Each sink module (`console`, `file`, and any future sink such as a
remote shipper) exposes an `add_*_sink(...) -> int` function that
attaches a `loguru` handler and returns its handler id. `remove_sink`
detaches any sink by that id, regardless of which module added it.
Adding a new sink means adding a new module here — never a change to
`LoggingService`, `Logger`, or `LoggingManager`'s public shape.
"""

from loguru import logger as _loguru_logger


def remove_sink(sink_id: int) -> None:
    """Detach a previously-added sink by id."""
    _loguru_logger.remove(sink_id)
