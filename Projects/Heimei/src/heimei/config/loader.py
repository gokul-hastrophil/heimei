from pathlib import Path
from typing import Any

import yaml

from heimei.config.errors import ManifestNotFoundError, ManifestParseError


def load_manifest(path: Path) -> dict[str, Any]:
    """Read and parse a manifest YAML file into a raw dict.

    This is the only function in Heimei allowed to parse manifest YAML
    directly. Everything downstream (validation, models, services,
    consumers) works with typed Pydantic models instead.
    """
    if not path.is_file():
        raise ManifestNotFoundError(path)

    try:
        raw = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        raise ManifestParseError(path, str(exc)) from exc

    if raw is None:
        return {}

    if not isinstance(raw, dict):
        raise ManifestParseError(
            path,
            f"expected a YAML mapping at the top level, got {type(raw).__name__}",
        )

    return raw
