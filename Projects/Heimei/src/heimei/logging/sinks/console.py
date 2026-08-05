import sys

from loguru import logger as _loguru_logger

_FORMAT = (
    "<green>{time:HH:mm:ss}</green> <level>{level: <8}</level> "
    "<cyan>{extra}</cyan> {message}"
)


def add_console_sink(*, level: str = "INFO") -> int:
    """Attach a human-readable, colorized console sink. Returns its sink id.

    Removes loguru's default stderr sink first — otherwise every record
    would be printed twice (once in loguru's default format, once in
    ours). This is the console sink's job because it always runs first,
    during LoggingManager.initialize().
    """
    _loguru_logger.remove()
    return _loguru_logger.add(sys.stderr, level=level, colorize=True, format=_FORMAT)
