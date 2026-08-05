from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfigPaths(BaseSettings):
    """Resolves where Heimei's manifest files live on disk.

    Defaults to ``~/Heimei/System/manifest``, the workspace layout
    documented in ``Knowledge/Documentation/heimei-architecture-notes.md``.
    Override with the ``HEIMEI_HOME`` environment variable to point at a
    different workspace root, e.g. on a machine with a non-default layout.
    """

    model_config = SettingsConfigDict(env_prefix="HEIMEI_")

    home: Path = Field(default_factory=lambda: Path.home() / "Heimei")

    @property
    def manifest_dir(self) -> Path:
        return self.home / "System" / "manifest"
