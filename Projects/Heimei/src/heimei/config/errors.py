from pathlib import Path

from pydantic_core import ErrorDetails


class ConfigurationError(Exception):
    """Base class for all Configuration Manager errors."""


class ManifestNotFoundError(ConfigurationError):
    def __init__(self, path: Path):
        self.path = path
        super().__init__(f"Manifest file not found: {path}")


class ManifestParseError(ConfigurationError):
    def __init__(self, path: Path, reason: str):
        self.path = path
        self.reason = reason
        super().__init__(f"Failed to parse manifest {path}: {reason}")


class ManifestValidationError(ConfigurationError):
    def __init__(self, path: Path, errors: list[ErrorDetails]):
        self.path = path
        self.errors = errors
        details = "\n".join(
            f"  - {'.'.join(str(loc) for loc in err['loc']) or '<root>'}: {err['msg']}"
            for err in errors
        )
        super().__init__(f"Manifest {path} failed validation:\n{details}")
