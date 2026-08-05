# ADR-0008: Configuration Manager

Status: Accepted

Version: 1.2 (frozen 2026-08-05 — see Decision, "Revision (v1.2)")

Date: 2026-08-05

Author: Gokul

Stability: Frozen. `heimei.config`'s public API (below) is closed to new functionality. Extend Configuration by adding a new manifest model in the subsystem that owns it and calling `ConfigurationService.get()` with it — never by modifying this package. If a change here ever looks necessary for a new manager, that's a signal to re-read this ADR first.

---

## Context

Heimei subsystems (agents, memory, models, core, etc.) each need configuration, and that configuration is expressed as manifest YAML files under `System/manifest/` (e.g. `machine.yaml`). Before this decision, no code owned reading or validating those files — the shape of `machine.yaml` existed only by convention, and any subsystem that needed it would have had to parse YAML itself with no shared validation or error handling.

---

## Problem Statement

Heimei needs a single, typed, testable way to load manifest YAML and hand it to consumers, so that:

- No subsystem parses YAML directly or re-implements validation.
- Configuration errors (missing file, malformed YAML, wrong shape) produce clear, actionable messages instead of raw parser tracebacks.
- Repeated access to configuration doesn't re-read and re-parse the filesystem.
- New manifests can be added later (per subsystem) without redesigning the pipeline.

---

## Decision

Implement a Configuration Manager as the `heimei.config` package, structured as a fixed pipeline:

`Manifest YAML -> Loader -> Validation -> Pydantic Models -> Configuration Service -> Consumers`

- `loader.py` exposes a single function, `load_manifest(path)`, the only code in Heimei allowed to call `yaml.safe_load`. It turns filesystem/YAML failures into typed errors (`ManifestNotFoundError`, `ManifestParseError`).
- `models.py` defines a Pydantic model per manifest — currently only `MachineManifest`, for `machine.yaml`, the only manifest with real content today. There is deliberately no aggregate "all configuration" model; each subsystem's model stands alone.
- `service.py` (`ConfigurationService`) exposes one generic method, `get(name, model, *, force=False)`, which loads `<manifest_dir>/<name>.yaml`, validates it against the caller-supplied model, and caches the result keyed by `name`. `get_configuration_service()` is a process-wide singleton for consumers to share the cache; `reset_configuration_service()` clears it. The constructor takes only `manifest_dir` — nothing else.
- `settings.py` (`ConfigPaths`, internal) resolves the manifest directory from the `HEIMEI_HOME` environment variable (default `~/Heimei`), keeping the workspace-root assumption in one place per the multi-machine requirement in `Knowledge/Documentation/Standards.md`.
- The CLI (`heimei config show|validate|dump`) is a consumer of the service like any other subsystem would be — it does not touch YAML or the filesystem directly. It calls `service.get("machine", MachineManifest, force=True)` itself; `ConfigurationService` has no `machine`-specific knowledge at all.

**Frozen public API**, the full contract any future manager may depend on:

```text
ConfigurationService(manifest_dir: Path | None = None)
ConfigurationService.manifest_dir -> Path
ConfigurationService.get(name: str, model: type[M], *, force: bool = False) -> M
get_configuration_service() -> ConfigurationService
reset_configuration_service() -> None
MachineManifest, PlatformInfo, HardwareInfo, NetworkInfo
ConfigurationError, ManifestNotFoundError, ManifestParseError, ManifestValidationError
```

**Revision (v1.1, same day):** the first pass had `ConfigurationService.load()` build one aggregate `HeimeiConfig` model holding every manifest. That means adding a manifest for any future subsystem (agents, memory, ...) would require editing `HeimeiConfig`, adding a private loader method, and changing `load()` — all in the shared config package every other subsystem also depends on. Revised to the generic `get(name, model)` before any other subsystem could couple to the old shape: adding a manifest now means the *owning* subsystem defines its own model and calls `get()` with it, with no change to `heimei.config` at all. `ManifestLoader` (a one-method class) also became the plain `load_manifest` function, and the public API (`heimei.config.__init__`) was narrowed to drop `ManifestLoader`/`ConfigPaths`/`HeimeiConfig` — subsystems depend on `ConfigurationService` and their own models, not on loading/path-resolution internals.

**Revision (v1.2, same day — freeze pass):** with the shape settled, did one more pass looking for anything unnecessary before declaring the API stable, and found two remaining cracks:

- `ConfigurationService.__init__` took an injectable `loader` callable (a seam for swapping `load_manifest`). Nothing ever used it — every test injects via `manifest_dir` instead — so it was dead public surface. Removed; the constructor now takes only `manifest_dir`.
- `ConfigurationService.machine` was a convenience property wrapping `get("machine", MachineManifest)`. It reintroduced exactly the kind of manifest-specific knowledge into the generic service that the v1.1 revision had just removed at the aggregate-model level — and it was already unused: the real CLI consumer called `get()` directly, never `.machine`. Removed; `MachineManifest` access goes through `get()` like any other manifest, with no special case in the service.

With those gone, `ConfigurationService` has zero knowledge of `machine` or any other specific manifest — the generic principle from v1.1 now holds all the way down, not just at the top level.

---

## Architecture

```text
System/manifest/<name>.yaml
        |
        v
load_manifest(path)                 -- raises ManifestNotFoundError / ManifestParseError
        |
        v
<SomeManifest>.model_validate()     -- raises ManifestValidationError (wraps pydantic ValidationError)
        |
        v
ConfigurationService.get(name, SomeManifest)
    - caches the validated model, keyed by manifest name
    - force=True bypasses the cache for one call
        |
        v
Consumers (CLI: heimei config show|validate|dump, via get("machine", MachineManifest);
           future: other subsystems calling get("<their-name>", <TheirModel>))
```

---

## Alternatives Considered

### Option 1: Let each subsystem load its own YAML with `yaml.safe_load`

Pros

- No shared abstraction to build or maintain.

Cons

- Violates the "no subsystem parses YAML directly" requirement.
- Validation, error messages, and caching would be duplicated (or skipped) per subsystem.

### Option 2: `pydantic-settings` `YamlConfigSettingsSource` directly on each subsystem's settings class

Pros

- Less code; pydantic-settings already knows how to read YAML.

Cons

- Couples configuration *loading* to configuration *usage* in every subsystem instead of centralizing it in one service.
- Harder to give manifest-specific error messages (which file, which field) since the settings source swallows that context.
- Doesn't give a single place to cache or to add cross-manifest validation later.

---

## Consequences

Positive

- Exactly one place (`heimei.config`) knows how to read and validate manifest YAML; adding a manifest for a new subsystem means that subsystem defining one model and calling `get()`, with zero changes to `heimei.config` itself.
- Errors are typed and carry the failing path, making CLI output and future logging clear.
- Caching means repeated `get("machine", MachineManifest)` calls in one process are a single filesystem read, and each manifest's cache entry is independent — one subsystem's `force=True` refresh doesn't invalidate another's.
- The public API (`heimei.config.__init__`) only exposes what a subsystem actually needs (`ConfigurationService`, `get_configuration_service`, `reset_configuration_service`, models, errors), so there's less surface to keep stable as more subsystems start depending on it.

Negative

- One more layer of indirection versus a subsystem reading its own YAML.
- `get()`'s cache is keyed by manifest name only; if two callers ever passed different model classes for the same name, the second caller's validated result would not come from the first caller's cache entry (guarded by an `isinstance` check, exercised in `tests/test_config_service.py`) — a reminder that manifest names are expected to map to exactly one model.

Trade-offs

- Manifest models use `extra="forbid"`, so an unrecognized field in a manifest is a hard validation error rather than being silently ignored. This is intentional (fail loudly on drift) but means every new manifest field needs a matching model change before it's usable.

---

## Future Work

Configuration itself is frozen (see Stability, above) — the items below extend it through the sanctioned path (new manifest models) or belong to other subsystems, not to `heimei.config`.

- Typed models for the remaining manifests once their shape is decided: `agents.yaml`, `memory.yaml`, `models.yaml`, `network.yaml`, `software.yaml`, `system.yaml` (all currently empty placeholders). Each is a model defined by its owning subsystem plus a `get("<name>", <Model>)` call — no change to `heimei.config` required.
- A `--manifest-dir` override or per-machine manifest directory resolution if Heimei ever runs from a non-standard `HEIMEI_HOME` layout in practice (today only the env var override exists).
- If a CLI command ever needs to show/dump *all* known manifests at once (not just `machine`), that command will need its own small registry of `(name, model)` pairs to iterate — deliberately not built into `ConfigurationService` until there's a second manifest to justify it.

---

## References

Related ADRs: none yet reference this one.

Documentation: `Knowledge/Documentation/Standards.md` (Python conventions, multi-machine requirement), `Knowledge/Documentation/heimei-architecture-notes.md` (data-directory vs. code pattern), `Projects/Heimei/src/heimei/config/` (implementation), `Projects/Heimei/tests/test_config_*.py` (tests).
