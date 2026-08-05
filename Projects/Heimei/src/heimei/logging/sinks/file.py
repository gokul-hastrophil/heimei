from pathlib import Path

from loguru import logger as _loguru_logger


def add_file_sink(path: Path, *, level: str = "INFO") -> int:
    """Attach a structured (JSON lines) file sink at `path`. Returns its sink id."""
    path.parent.mkdir(parents=True, exist_ok=True)
    return _loguru_logger.add(path, level=level, serialize=True)
