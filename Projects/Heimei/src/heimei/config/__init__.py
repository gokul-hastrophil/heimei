"""Configuration Manager: the single source of truth for Heimei configuration.

This is a frozen, foundational subsystem (see ``System/docs/Architecture/
0008-configuration.md``). Its public contract for consumers is exactly:

- ``get_configuration_service()`` for the shared, cached service.
- ``ConfigurationService`` if a subsystem needs its own instance (e.g. tests).
- ``ConfigurationService.get(name, model)`` to load and validate a manifest
  by name against a Pydantic model owned by the calling subsystem.
- ``reset_configuration_service()`` to drop the shared instance (mainly for
  tests).
- The error hierarchy below to catch and report configuration failures.

Extend Configuration by adding a new manifest model in the subsystem that
owns it and calling ``get()`` with it — never by modifying this package.
``load_manifest`` and manifest-directory resolution are internal to
``ConfigurationService`` and intentionally not part of this public surface
— subsystems should not parse YAML or resolve paths themselves.
"""

from heimei.config.errors import (
    ConfigurationError,
    ManifestNotFoundError,
    ManifestParseError,
    ManifestValidationError,
)
from heimei.config.models import (
    HardwareInfo,
    MachineManifest,
    NetworkInfo,
    PlatformInfo,
)
from heimei.config.service import (
    ConfigurationService,
    get_configuration_service,
    reset_configuration_service,
)

__all__ = [
    "ConfigurationError",
    "ManifestNotFoundError",
    "ManifestParseError",
    "ManifestValidationError",
    "HardwareInfo",
    "MachineManifest",
    "NetworkInfo",
    "PlatformInfo",
    "ConfigurationService",
    "get_configuration_service",
    "reset_configuration_service",
]
