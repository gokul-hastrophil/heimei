from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from heimei.config.errors import ManifestValidationError
from heimei.config.loader import load_manifest
from heimei.config.settings import ConfigPaths

ManifestModel = TypeVar("ManifestModel", bound=BaseModel)


class ConfigurationService:
    """Single source of truth for Heimei configuration.

    Loads manifest YAML from disk, validates it into a caller-supplied
    Pydantic model, and caches the result per manifest name so repeated
    access doesn't re-read or re-parse the filesystem. Consumers should go
    through this service (or the module-level
    ``get_configuration_service()`` singleton) rather than reading
    manifest files directly.

    Deliberately has no knowledge of any specific manifest (not even
    ``machine``): adding a new manifest for a subsystem (agents, memory,
    ...) means that subsystem defines its own Pydantic model and calls
    ``get("its-manifest-name", ItsModel)`` — never a change to this class.
    """

    def __init__(self, manifest_dir: Path | None = None):
        self._manifest_dir = manifest_dir or ConfigPaths().manifest_dir
        self._cache: dict[str, BaseModel] = {}

    @property
    def manifest_dir(self) -> Path:
        return self._manifest_dir

    def get(
        self,
        name: str,
        model: type[ManifestModel],
        *,
        force: bool = False,
    ) -> ManifestModel:
        """Return ``<manifest_dir>/<name>.yaml`` validated as ``model``.

        Cached per manifest name. Pass ``force=True`` to bypass the cache
        and re-read from disk (e.g. for ``heimei config validate``).
        """
        cached = self._cache.get(name)
        if not force and isinstance(cached, model):
            return cached

        path = self._manifest_dir / f"{name}.yaml"
        raw = load_manifest(path)
        try:
            validated = model.model_validate(raw)
        except ValidationError as exc:
            raise ManifestValidationError(path, exc.errors()) from exc

        self._cache[name] = validated
        return validated


_service: ConfigurationService | None = None


def get_configuration_service() -> ConfigurationService:
    """Return the process-wide ConfigurationService singleton."""
    global _service
    if _service is None:
        _service = ConfigurationService()
    return _service


def reset_configuration_service() -> None:
    """Drop the process-wide ConfigurationService singleton.

    The next ``get_configuration_service()`` call builds a fresh one.
    Mainly for tests that change ``HEIMEI_HOME`` or manifest contents
    between cases; a long-running consumer that just wants fresh data
    should prefer ``service.get(name, model, force=True)``.
    """
    global _service
    _service = None
