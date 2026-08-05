import os
from pathlib import Path

from heimei.config import ConfigurationService
from heimei.core.context import RuntimeContext
from heimei.core.health import HealthState, HealthStatus
from heimei.logging.manifest import LoggingManifest
from heimei.logging.service import LoggingService
from heimei.logging.sinks import remove_sink
from heimei.logging.sinks.console import add_console_sink
from heimei.logging.sinks.file import add_file_sink


def _resolve_log_path(directory: str | None) -> Path:
    home = Path(os.environ.get("HEIMEI_HOME", str(Path.home() / "Heimei")))
    relative = Path(directory) if directory else Path("State") / "Logs"
    return home / relative / "heimei.log"


class LoggingManager:
    """Implements the Manager lifecycle (ADR-0011) for Heimei's logging.

    Configuration is the single source of truth for sink settings: this
    loads ``LoggingManifest`` from ``System/manifest/logging.yaml`` via
    the existing, unmodified ``ConfigurationService.get(name, model)``
    during ``initialize()`` — the first manifest besides ``machine`` to
    use that path. The console sink is attached during ``initialize()``
    — it needs no open/close lifecycle, so configuring it is wiring, not
    activation. The file sink is attached during ``startup()`` — it
    opens a real file handle, which is exactly what ``startup()``/
    ``shutdown()`` exist to bracket. See ADR-0012.
    """

    name = "logging"
    dependencies: tuple[str, ...] = ()

    def __init__(self) -> None:
        self.service = LoggingService()
        self._manifest: LoggingManifest | None = None
        self._console_sink_id: int | None = None
        self._file_sink_id: int | None = None
        self._initialized = False
        self._shut_down = False

    def initialize(self, context: RuntimeContext) -> None:
        config = context.services.get(ConfigurationService)
        self._manifest = config.get("logging", LoggingManifest)

        if self._manifest.console:
            self._console_sink_id = add_console_sink(level=self._manifest.level)

        context.services.register(LoggingService, self.service)
        self._initialized = True

    def startup(self) -> None:
        assert self._manifest is not None
        if self._manifest.file:
            path = _resolve_log_path(self._manifest.directory)
            self._file_sink_id = add_file_sink(path, level=self._manifest.level)

    def health(self) -> HealthStatus:
        if not self._initialized or self._shut_down:
            return HealthStatus(state=HealthState.UNHEALTHY, detail="logging is not active")
        return HealthStatus(state=HealthState.HEALTHY)

    def shutdown(self) -> None:
        if self._file_sink_id is not None:
            remove_sink(self._file_sink_id)
            self._file_sink_id = None
        if self._console_sink_id is not None:
            remove_sink(self._console_sink_id)
            self._console_sink_id = None
        self._shut_down = True
