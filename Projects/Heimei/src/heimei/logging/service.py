from loguru import logger as _loguru_logger


class LoggingService:
    """Structured logging — the public interface every manager uses.

    Registered into the ServiceContainer by LoggingManager. Every other
    manager resolves this (never `print()`, stdout, or `loguru` itself)
    and calls its methods with a message plus structured keyword fields:

        logger.info("Runtime started", subsystem="runtime", manager="logging")

    This class and `heimei.logging.sinks` are the only places in Heimei
    allowed to import `loguru` directly. See ADR-0012.
    """

    def debug(self, message: str, **fields: object) -> None:
        _loguru_logger.bind(**fields).debug(message)

    def info(self, message: str, **fields: object) -> None:
        _loguru_logger.bind(**fields).info(message)

    def warning(self, message: str, **fields: object) -> None:
        _loguru_logger.bind(**fields).warning(message)

    def error(self, message: str, **fields: object) -> None:
        _loguru_logger.bind(**fields).error(message)

    def critical(self, message: str, **fields: object) -> None:
        _loguru_logger.bind(**fields).critical(message)
