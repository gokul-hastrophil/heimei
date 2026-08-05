"""Logging Manager: the single logging interface every Heimei manager uses.

See ``System/docs/Architecture/0012-logging-manager.md``. Public contract:

- ``Logger``: the structured-logging Protocol (debug/info/warning/error/critical).
- ``LoggingService``: the concrete implementation, registered into the
  ``ServiceContainer`` by ``LoggingManager`` — resolve it with
  ``context.services.get(LoggingService)``.
- ``LoggingManager``: the ``Manager`` lifecycle implementation. Loads
  ``LoggingManifest`` via the existing Configuration API during
  ``initialize()``, attaches the console sink there, and attaches the
  file sink during ``startup()``.
- ``LoggingManifest``: the typed schema for ``System/manifest/logging.yaml``.

Nothing outside this package touches ``loguru`` directly — not even the
rest of Heimei's own code. Sink configuration lives entirely under
``heimei.logging.sinks``; adding a future sink (e.g. remote logging)
means adding a module there, never changing ``Logger``, ``LoggingService``,
or ``LoggingManager``'s public shape.
"""

from heimei.logging.logger import Logger
from heimei.logging.manager import LoggingManager
from heimei.logging.manifest import LoggingManifest
from heimei.logging.service import LoggingService

__all__ = ["Logger", "LoggingManager", "LoggingManifest", "LoggingService"]
