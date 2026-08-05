# ADR-0012: Logging Manager

Status: Accepted

Version: 1.0 (implemented and frozen 2026-08-05 — see Decision, "Revision (v1.0)")

Date: 2026-08-05

Author: Gokul

Stability: Frozen. Implemented in `heimei.logging` and wired into `Application`, without modifying `heimei.config` or `heimei.core`. Treat as stable infrastructure, per the same discipline applied to ADR-0008 and ADR-0011 — extend by adding a sink module or a new consumer, not by changing `Logger`, `LoggingService`, or `LoggingManager`'s public shape.

---

## Context

`heimei.core` (ADR-0011) is now frozen, implemented infrastructure: `Application`, `ServiceContainer`, the `Manager` protocol, `RuntimeContext`, and `Runtime` exist and orchestrate lifecycle, but nothing has actually used the Container to share a real cross-cutting service yet — Configuration is registered into it, but nothing *depends on* it through the Container in practice. Logging Manager is the next subsystem to build, and it is the first real test of "future managers extend Heimei by becoming a Manager and/or Service, without touching Core Runtime" (ADR-0011, Stability).

Today, output happens in two uncoordinated ways: CLI commands print user-facing results directly via `rich.Console` (`heimei/cli/*.py`), and nothing else logs anything at all — there is no diagnostic/operational output from `heimei.config` or `heimei.core`. `pyproject.toml` already fixes `loguru` as the project's logging library (`Knowledge/Documentation/Standards.md`), but no code uses it, and nothing prevents a future manager from importing `loguru` (or stdlib `logging`, or a bare `print()`) directly and configuring it however it likes.

---

## Problem Statement

As more managers are built (Memory, Model Router, Agent System, ...), Heimei needs one place that owns:

- **Routing** — every manager's log records go somewhere consistent, without each manager configuring its own sinks.
- **Formatting** — a human-readable form for interactive use and a structured (machine-parseable) form for persistence, from the same log call.
- **Persistence** — structured logs land on disk, not just the console, so they survive past a single CLI invocation.
- **Structured logging** — a log call carries key-value context (which manager, what operation, what happened), not just a free-text message.
- **A future path to remote logging** — without redesigning the interface every manager already codes against.

And it needs to do this the same way Configuration Manager solved the equivalent problem for YAML (ADR-0008): **no subsystem should write directly to stdout, call `print()`, or import a third-party logging library — every manager logs through one interface, and only the Logging Manager itself touches `loguru`.**

---

## Decision

`heimei.logging` is a new, independent package — a peer of `heimei.config`, not a submodule of `heimei.core`. **Implementation required zero changes to `heimei.core` or `heimei.config`.** Logging Manager is purely a new consumer of the frozen `Manager`/`ServiceContainer`/`RuntimeContext` contract and the frozen `ConfigurationService.get(name, model)` contract, which is exactly what both freezes were for.

### 1. `Logger` — the one interface every manager codes against

```python
class Logger(Protocol):
    def debug(self, message: str, **fields: object) -> None: ...
    def info(self, message: str, **fields: object) -> None: ...
    def warning(self, message: str, **fields: object) -> None: ...
    def error(self, message: str, **fields: object) -> None: ...
    def critical(self, message: str, **fields: object) -> None: ...
```

`**fields` is the structured-logging surface — e.g. `logger.info("manifest loaded", manifest="machine", duration_ms=4)` — carried as key-value context alongside the message, not string-formatted into it. This is the only shape any manager ever sees; `loguru` itself never appears outside `heimei.logging`.

### 2. `LoggingManager` and `LoggingService` — a `Manager` that registers a `Service`

Implementation settled on a single shared `LoggingService` instance rather than a `get_logger(name)` factory (this ADR's original sketch, before implementation, had `LoggingManager.get_logger(name) -> Logger`). Every caller resolves the same `LoggingService` and passes its own identifying fields explicitly:

```python
class LoggingManager:
    name = "logging"
    dependencies: tuple[str, ...] = ()

    def initialize(self, context: RuntimeContext) -> None: ...
    def startup(self) -> None: ...
    def health(self) -> HealthStatus: ...
    def shutdown(self) -> None: ...

    service: LoggingService   # registered into the ServiceContainer during initialize()
```

`dependencies = ()`: Logging Manager needs the `ConfigurationService`, but that is a *Service* resolved via `context.services.get(ConfigurationService)`, not a Runtime-orchestrated *Manager* — Configuration was never registered as a Manager (ADR-0011, Revision v1.0), so there is nothing to declare a Runtime dependency on. This is the intended distinction the Core Runtime freeze already drew between "Manager dependency" (orders lifecycle) and "Service resolution" (works via the Container regardless of the dependency graph), and Logging Manager is the first real case that exercises it.

**Split across `initialize()`/`startup()`, staying inside the existing contract:**

- `initialize(context)` — resolve `ConfigurationService`, load `LoggingManifest` (see below), and — if `manifest.console` is true — attach the console sink at `manifest.level`. This does not violate ADR-0011's "no I/O beyond wiring" for `initialize()`: a console sink needs no open/close lifecycle of its own, and reading the logging manifest is the same category of config-resolution every manager's `initialize()` already does. Register `LoggingService` into the container: `context.services.register(LoggingService, self.service)`.
- `startup()` — if `manifest.file` is true, attach the file sink (opening the actual log file is a real I/O resource, which is exactly what `startup()`/`shutdown()` exist to bracket). A future remote sink would attach here too.
- `shutdown()` — detach whichever sinks were attached.
- `health()` — `UNHEALTHY` before `initialize()` has run or after `shutdown()`; `HEALTHY` otherwise. Simpler than this ADR's original sketch (which proposed a `DEGRADED` state for partial sink failure): with sink enablement now driven entirely by `manifest.console`/`manifest.file`, "a sink isn't attached" is either the configured, expected state (not unhealthy) or a `startup()` exception that propagates immediately (per ADR-0011, "no retry/suppression") rather than being caught and downgraded to `DEGRADED`. What counts as each state remains a manager's own judgment, per ADR-0011 section 4.

**Known, disclosed limitation, confirmed by implementation:** because Core Runtime runs `initialize()` on *every* manager before `startup()` on *any* manager, no manager's persistent (file) logging is active during any manager's `initialize()` phase — including Logging Manager's own. Log calls made during `initialize()` reach the console sink only (verified by `tests/test_logging_manager.py::test_log_calls_before_startup_do_not_reach_the_file`). This is a consequence of the already-frozen Runtime, not something this ADR works around; whether it's worth solving (e.g. buffering early records) remains Future Work.

### 3. Configuration extends through a new manifest — validating ADR-0008's own design

Logging Manager defines its own model (`heimei.logging.manifest.LoggingManifest`) and loads it via the existing, frozen `ConfigurationService.get(name, model)` — exactly the extension path ADR-0008 was built for, and the first manifest to actually use it besides `machine`:

```python
class LoggingManifest(BaseModel):
    level: str = "INFO"
    console: bool = True
    file: bool = True
    directory: str | None = None   # relative to HEIMEI_HOME, e.g. "State/Logs"
```

resolved as `config.get("logging", LoggingManifest)`. `System/manifest/logging.yaml` was created as part of implementation — the first new manifest file since `machine.yaml`:

```yaml
level: INFO
console: true
file: true
directory: State/Logs
```

(`file` defaults to `True` in the model, not `False` as this ADR originally sketched — the out-of-the-box behavior matches what the pre-manifest implementation already did unconditionally, so shipping the manifest didn't silently change default behavior.)

### 4. Persistence location

Logs are machine-generated, ephemeral-by-design output — exactly what `Knowledge/Documentation/Glossary.md` defines `State/` to hold. Proposed location: a new `State/Logs/` subdirectory (PascalCase, matching the convention `Knowledge/Documentation/Standards.md` already establishes for new `State/` categories), resolved from `HEIMEI_HOME` the same way Configuration resolves `System/manifest/` — independently of `heimei.config`'s internal (and frozen) `ConfigPaths`, since that class is private to the Configuration package.

### 5. Format

Two representations from the same log call, not two logging systems: a human-readable, colorized line for the console sink (interactive use, matching the project's existing `rich`-based CLI aesthetic), and structured JSON lines for the file sink (machine-parseable, ready for a future remote shipper to consume without reformatting).

### Scope boundary: this is not about CLI output

`heimei config show`'s table, `heimei version`'s version string, and similar are a command's **primary result** — the answer to what the user asked for — not diagnostic telemetry, and they are out of scope for this ADR. They continue to print directly via `rich.Console`, unchanged. "No subsystem should write to stdout / use a third-party logger" governs *internal operational logging* (what a manager reports about its own behavior, errors, and events), not a CLI command's user-facing output. A future `heimei logs tail`-style command would be *presenting already-logged data* to a user — legitimate CLI output *about* logs, not itself logging.

### Revision (v1.0, same day — implemented and frozen)

Implementation was approved and completed in two passes:

1. **First pass** (`heimei.logging` package, sinks, `LoggingService`, `LoggingManager` with hardcoded/constructor-level config) — no `heimei.config` or `heimei.core` changes.
2. **Follow-up pass**, approved separately: (a) `Application.__init__` now does `self.runtime.register(LoggingManager())` — the one edit inside `heimei/core/application.py`, sanctioned because it only calls the existing, frozen `Runtime.register()` and changes no behavior of `Runtime`/`ServiceContainer`/`Manager`/`RuntimeContext` themselves; (b) `LoggingManager.initialize()` now loads `LoggingManifest` via `ConfigurationService.get("logging", LoggingManifest)` instead of constructor arguments, and `System/manifest/logging.yaml` was created — both changes entirely inside `heimei.logging`, using `heimei.config`'s existing public API.

Three deviations from this ADR's original (pre-implementation) sketch, all filling in detail the ADR itself had flagged as illustrative/not frozen, not architectural problems:

- No `get_logger(name)` factory. A single shared `LoggingService` is registered; callers pass their own identifying fields explicitly (see the example in Problem Statement). Simpler, and it's what was actually specified at implementation time.
- `LoggingManifest.file` defaults to `True`, not `False`, to match pre-manifest default behavior (see section 3).
- `health()` has no `DEGRADED` path. With sink enablement driven entirely by manifest flags rather than runtime failure-catching, "not attached" is either expected (disabled by config) or an exception that propagates per ADR-0011 — there was no remaining case that actually needed a middle state.

No ADR update was needed for the underlying architecture — `heimei.config` and `heimei.core` required zero changes across both passes, confirming both freezes hold under a real second manager.

---

## Architecture

```text
Application.__init__
    services.register(ConfigurationService, get_configuration_service())
    runtime.register(LoggingManager())
        |
        v
System/manifest/logging.yaml
        |
        v  (loaded via the existing, frozen ConfigurationService.get("logging", LoggingManifest))
LoggingManifest(level, console, file, directory)
        |
        v
LoggingManager (a Manager; registers a Service)
    .initialize(context)   -- load manifest; if console: attach console sink; register LoggingService
    .startup()              -- if file: attach file sink (future: remote sink)
    .health()                -- UNHEALTHY before initialize()/after shutdown(); HEALTHY otherwise
    .shutdown()              -- detach whichever sinks were attached
        |
        v (context.services.register(LoggingService, self.service))
ServiceContainer                       -- unchanged, frozen (ADR-0011)
        |
        v (resolved by any other manager via context.services.get(LoggingService))
Other Managers (Memory, Model Router, Agent System, ...)
    each: logger = context.services.get(LoggingService)
    each: logger.info("did a thing", key=value, ...)  -- never print(), never import loguru directly
        |
        v
Sinks (heimei/logging/sinks/)
    console  -- human-readable, colorized, active from initialize() if manifest.console
    file     -- structured JSON lines, under State/Logs/, active from startup() if manifest.file
    (future) remote  -- same Logger interface, new sink module only
```

---

## Alternatives Considered

### Option 1: No Logging Manager — subsystems print or log ad hoc (status quo)

Pros

- Zero new code.

Cons

- Directly contradicts the stated requirement; no persistence, no structure, no consistent routing, and every manager reinvents its own approach.

### Option 2: Each subsystem imports and configures `loguru` (or stdlib `logging`) directly

Pros

- No new abstraction; `loguru` is already the fixed dependency.

Cons

- The exact problem Configuration Manager already solved for YAML, recreated for logging: no central control over format, level, or sinks; a third-party library exposed everywhere instead of behind one seam; adding remote logging later means touching every subsystem instead of one sink definition.

### Option 3 (recommended): `LoggingManager` as a `Manager` + `Service`, `Logger` protocol as the only surface, sink-based routing

Pros

- Matches the precedent already set twice (Configuration for YAML, Core Runtime's Manager/Service split for orchestration) — a new manager plugging into frozen infrastructure without changing it.
- `Logger`'s structured `**fields` interface supports today's console/file sinks and a future remote sink without changing what any manager's code looks like.
- Validates two things at once: that `ConfigurationService.get(name, model)` really does support a second manifest with zero changes to `heimei.config`, and that `heimei.core`'s Manager/Service split really does support a second manager with zero changes to `heimei.core`.

Cons

- The `initialize()`-phase / `startup()`-phase split means early (initialize-time) log records never reach the file sink in v1 — a real, disclosed gap, not solved here.

---

## Consequences

Positive

- Every future manager gets structured, routed, persisted logging by calling `context.services.get(LoggingService)` — no manager ever touches `loguru`, `print()`, or stdout directly.
- Remote logging (explicitly required eventually) is "add a sink," not "redesign the interface" — every manager's logging code is already written against the final shape.
- Two more pieces of frozen infrastructure (`heimei.config`, `heimei.core`) get validated by a real second consumer instead of remaining single-use designs.

Negative

- One more manager every future subsystem is expected to depend on for anything beyond trivial internal state, alongside Configuration.
- The initialize-phase logging gap (console-only, no file persistence) is a real limitation a developer debugging early startup issues needs to know about.

Trade-offs

- `Logger`'s five-level, `**fields`-only interface is deliberately coarse — no spans/tracing, no per-call sink override, no async logging. A manager needing more exposes that through its own code, not by extending the shared interface, mirroring how `HealthStatus` stayed coarse in ADR-0011.
- Console and file sinks are proposed now because both have an immediate, real use (interactive CLI use today; persistence is explicitly required); remote logging is deferred entirely rather than half-designed, per the same discipline ADR-0011 applied to its own deferred event bus/scheduler/plugins.

---

## Future Work

Logging itself is frozen (see Stability, above) — the items below extend it through a new sink module or a new consumer, or belong to other subsystems, not to a change in `heimei.logging`'s existing public shape.

- Remote/network logging sink — explicitly anticipated, not designed here; should require adding a sink, not touching `Logger`, `LoggingService`, or any manager's calling code.
- Deciding whether early (any manager's `initialize()`-phase) log records should be buffered and flushed once the file sink attaches, or are simply accepted as console-only — only worth solving if debugging a real startup issue proves the gap actually matters (confirmed present, not yet hit in practice).
- `heimei logs` (or similar) CLI for viewing persisted/structured logs — out of scope for this ADR (see Scope boundary, above).
- Log rotation/retention policy for `State/Logs/` — not designed here; a single growing file is what's implemented; revisit only if disk usage or lookback needs become a real problem.

---

## References

Related ADRs: ADR-0008 (Configuration Manager — the manifest-extension mechanism this ADR is the first real user of), ADR-0011 (Core Runtime — the frozen Manager/Service/Runtime contract this ADR builds on without modifying).

Documentation: `Knowledge/Documentation/Standards.md` (fixes `loguru` as the logging dependency), `Knowledge/Documentation/Glossary.md` ("State" definition — the basis for `State/Logs/`), `Projects/Heimei/src/heimei/logging/` (implementation), `Projects/Heimei/tests/test_logging_*.py` (tests), `System/manifest/logging.yaml` (the manifest).
