from pydantic import BaseModel, ConfigDict


class LoggingManifest(BaseModel):
    """Typed schema for ``System/manifest/logging.yaml``. See ADR-0012.

    Loaded via the existing, unmodified ``ConfigurationService.get(name,
    model)`` — the first manifest besides ``machine`` to use that path.
    """

    model_config = ConfigDict(extra="forbid")

    level: str = "INFO"
    console: bool = True
    file: bool = True
    directory: str | None = None
