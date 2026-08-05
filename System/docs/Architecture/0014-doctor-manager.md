# ADR-0014: Doctor Manager

Status: Accepted

Version: 1.0 (implemented and frozen 2026-08-05 — see Decision, "Revision (v1.0)")

Date: 2026-08-05

Author: Gokul

Stability: Frozen. Implemented in `heimei.doctor` exactly as refined below, wired into `Application`, without modifying `heimei.config`, `heimei.core`, `heimei.logging`, or `heimei.inventory`. Treat as stable infrastructure, per the same discipline applied to ADR-0008/0011/0012/0013 — extend by adding a check file or a new consumer, not by changing `DoctorService`'s three responsibilities, `HealthCheck`'s signature, or `Finding`'s shape.

---

## Context

Four managers now exist on the frozen `heimei.core` Runtime/ServiceContainer contract: Configuration (ADR-0008), Core Runtime itself (ADR-0011), Logging (ADR-0012), and Inventory (ADR-0013, wired into `Application`). `heimei/doctor/` has existed as an empty stub since the initial bootstrap — `__init__.py`, `base.py`, `registry.py`, all empty — and `heimei/cli/doctor.py` currently just prints "Doctor subsystem is under development." The stub file *names* already anticipated this design almost exactly: `base.py` for the shared contract, `registry.py` for whatever runs against it.

Both ADR-0008 and ADR-0013 explicitly deferred a specific responsibility to "a future Doctor manager": comparing live, discovered state (`InventoryService`) against static, declared state (`ConfigurationService`'s `MachineManifest`). This ADR is that manager — but scoped narrower than that full deferral: Doctor is built here **entirely on top of Inventory**, evaluating Inventory snapshots on their own terms. The Configuration reconciliation remains a named Future Work item, not part of this design.

This ADR was approved with two refinements before implementation, applied below and detailed in "Revision (v1.0)": (1) individual checks receive `InventoryService` directly, never the `ServiceContainer`, and `DoctorService` resolves `InventoryService` exactly once; (2) every `Finding` carries a `category` field.

---

## Problem Statement

Heimei needs a health-analysis engine that:

- **Never queries the operating system directly** — Doctor's only source of machine facts is `InventoryService`.
- **Never mutates the system** — Doctor diagnoses; it does not repair, configure, or install anything.
- Evaluates Inventory snapshots against a set of **rules** ("checks") and produces structured, categorized **findings**.
- Is **extensible**: adding a new check must not require modifying a shared rules file, a big conditional, or the engine itself.
- Treats each check as **independent** (no check knows about another, the engine, or how services are resolved) and **composable** (the engine can run any subset — by name or by category — and one check failing must not prevent the others from reporting).

---

## Decision

Introduce real content for `heimei.doctor`: `base.py` holds the shared contract; `registry.py` holds pure check storage; `service.py` holds the rule engine (`DoctorService`); `manager.py` holds the `Manager` lifecycle implementation; `checks/*.py` holds independent, individual checks — the third instance of the "one file, one responsibility, no cross-awareness" pattern (after Logging's `sinks/` and Inventory's `collectors/`).

### 1. `base.py` — the shared contract every check and finding uses

```python
class Severity(Enum):
    OK = "ok"
    WARNING = "warning"
    CRITICAL = "critical"

class Category(Enum):
    HARDWARE = "hardware"
    SOFTWARE = "software"
    GPU = "gpu"
    DOCKER = "docker"
    STORAGE = "storage"
    NETWORK = "network"
    CONFIGURATION = "configuration"
    PERFORMANCE = "performance"

class Finding(BaseModel):
    check: str
    category: Category
    severity: Severity
    message: str
    detail: dict[str, object] | None = None
    evaluated_at: datetime

class HealthCheck(Protocol):
    name: str
    category: Category
    def run(self, inventory: InventoryService) -> tuple[Finding, ...]: ...
```

**`Severity` is deliberately distinct from `heimei.core.health.HealthState`** — a Manager's own operational health and a judgment about the machine are different questions (ADR-0013 already flagged this exact confusion risk for `InventoryManager.health()`; this extends the same discipline to Doctor).

**`Category` was added per explicit refinement.** Eight values (Hardware, Software, GPU, Docker, Storage, Network, Configuration, Performance) — v1's six built-in checks use six of them (CPU→Hardware, Memory→Performance, Storage→Storage, Network→Network, GPU→GPU, Docker→Docker); Software and Configuration are reserved for checks not built in this pass (see Future Work). Category enables `DoctorService.run(category=...)` filtering.

**`HealthCheck.run` receives `InventoryService` directly, never the `ServiceContainer`.** This replaces this ADR's original (pre-refinement) design, which passed the whole `ServiceContainer` so a future data source could be added without a signature change. The refinement's stated reasoning — "this keeps checks independent of the platform" — is upheld here literally: a check imports nothing from `heimei.core`, doesn't know a `ServiceContainer` exists, and can't accidentally resolve something outside its stated remit. The cost (adding a second data source later means changing `HealthCheck`'s signature) is accepted deliberately; see Alternatives.

### 2. `checks/` — independent, composable rules

```
heimei/doctor/checks/
    cpu.py       -- Category.HARDWARE
    memory.py      -- Category.PERFORMANCE
    storage.py       -- Category.STORAGE
    network.py         -- Category.NETWORK
    gpu.py               -- Category.GPU
    docker.py              -- Category.DOCKER
```

Each module exposes one class satisfying `HealthCheck` (`name`, `category`, `run(inventory)`). A check never imports another check, `registry.py`, `service.py`, or anything from `heimei.core`. It calls `InventoryService` methods directly — never `psutil`, `platform`, or any OS-facing library.

A concrete example, showing what "produces zero or more Findings" and "consumes only the inventory data it needs" mean in practice — the GPU check derives a real diagnostic purely from Inventory's own provenance field:

```python
class GpuCheck:
    name = "GPU"
    category = Category.GPU

    def run(self, inventory: InventoryService) -> tuple[Finding, ...]:
        gpu = inventory.gpu(refresh=True)
        if not gpu.available:
            return (ok_finding("No GPU detected"),)
        if gpu.source in ("pynvml", "nvidia-smi"):
            return (ok_finding(f"GPU driver functioning ({gpu.source})"),)
        # source == "lspci": visible on the PCI bus, but the two more
        # capable layers (which would succeed if the driver stack were
        # healthy) both failed.
        if any("nvidia" in d.name.lower() for d in gpu.devices):
            return (critical_finding("NVIDIA driver missing"),)
        return (ok_finding(f"GPU detected via lspci ({gpu.devices[0].name})"),)
```

Checks reading a volatile Inventory category pass `refresh=True` — a diagnostic check reporting stale cached data would be misleading. This is a convention each check follows, not something the engine enforces.

### 3. `registry.py` and `service.py` — storage, and the rule engine, kept separate

```python
# registry.py — pure storage, no orchestration logic
class CheckRegistry:
    def register(self, check: HealthCheck) -> None: ...   # raises DuplicateCheckError
    def get(self, name: str) -> HealthCheck: ...            # raises CheckNotFoundError
    def all(self) -> tuple[HealthCheck, ...]: ...
    def by_category(self, category: Category) -> tuple[HealthCheck, ...]: ...

# service.py — the rule engine
class DoctorService:
    def __init__(self, inventory: InventoryService) -> None: ...
    def register(self, check: HealthCheck) -> None: ...
    def run(self, *, category: Category | None = None, check: str | None = None) -> tuple[Finding, ...]: ...
```

**`DoctorService` resolves `InventoryService` exactly once — at construction — per explicit refinement.** It is handed to `__init__`, stored, and reused for every check on every `run()` call; no check, and no later point in `run()`, ever resolves it again. `CheckRegistry` is deliberately a separate class from `DoctorService`: registry is pure storage (register/get/list/filter), engine is orchestration (deciding which checks to run, running them, catching their failures) — splitting them means adding, say, dependency-ordering between checks later would touch only `registry.py`, never `service.py`'s failure-isolation logic, or vice versa.

`run()`'s three responsibilities are exactly as specified: `run()` (everything), `run(category=...)`, `run(check=...)` — `check` takes precedence if both are given. **The engine does no business logic beyond this** — it does not interpret, filter by severity, sort, or aggregate; that's presentation logic (the CLI, or a future consumer), mirroring `Runtime`'s own "no business logic" principle.

**A check that raises does not abort the run.** `DoctorService.run()` catches an exception from an individual check and converts it into a synthetic `Finding` (`severity=CRITICAL`, naming the check and the error) rather than propagating — a deliberate, narrow departure from Core Runtime's "a failure propagates" principle, justified because a broken check is itself a fact worth surfacing, and letting it silently block every *other* independent check from reporting would contradict "individual health checks should be independent." Fault *isolation*, not error *suppression* — the failure is still visible, just as a Finding.

### 4. `DoctorManager` — registers `DoctorService` and every built-in check, explicitly

```python
class DoctorManager:
    name = "doctor"
    dependencies: tuple[str, ...] = ("logging", "inventory")

    def initialize(self, context: RuntimeContext) -> None: ...
    def startup(self) -> None: ...
    def health(self) -> HealthStatus: ...
    def shutdown(self) -> None: ...

    service: DoctorService | None
```

`initialize()` resolves `LoggingService` (and logs its own initialization — a real exercise of the dependency, not a declared-but-unused one), resolves `InventoryService` exactly once, constructs `DoctorService(inventory)`, and explicitly registers all six built-in checks — no auto-discovery, no plugins, matching `ServiceContainer`'s own ban on auto-discovery (ADR-0011). `startup()`/`shutdown()` are no-ops (no connection or resource for a rule engine to open or close). `DoctorManager.health()` is the manager's own operational health, never a machine-health judgment — that lives entirely in `Finding.severity`.

### 5. Scope (unchanged from proposal)

Doctor never queries the OS directly, never mutates the system, is built entirely on top of Inventory for this ADR (no check resolves Configuration), and produces findings, not actions.

### 6. CLI: `heimei doctor`

```
✔ CPU
✔ Memory
✔ Docker
⚠ Disk usage high
✖ NVIDIA driver missing
```

For each check, if it produced any non-OK finding, each is printed with its own icon and message; otherwise one `✔ <check name>` line. Exit code is 1 if any `CRITICAL` finding exists, 0 otherwise (warnings alone don't fail the command). `heimei/cli/doctor.py` resolves `DoctorService` via `ctx.obj.services.get(DoctorService)` — see Revision (v1.0) for why `ctx.obj` needed to exist at all.

---

### Revision (v1.0, same day — approved with refinements, implemented and frozen)

**Two refinements applied before implementation:**

1. **`HealthCheck.run` takes `InventoryService`, not `ServiceContainer`** (Decision, section 1). Rejects the original design's `services: ServiceContainer` parameter in favor of the concrete service a check actually needs, trading future-extensibility-without-a-signature-change for real platform independence today.
2. **`Finding.category: Category` added** (Decision, section 1), with `DoctorService.run(category=...)` as the corresponding filter.

**Implementation matched the refined design, with three things discovered along the way:**

1. **A genuine circular import**, not merely a style question. `heimei.doctor.base`/`checks/*.py`/`service.py` originally imported `InventoryService` from `heimei.inventory` at module level, for type hints only. `heimei.inventory.__init__` imports `InventoryManager`, which imports `heimei.core.context` — and `heimei.core.__init__` eagerly imports `Application` (a pre-existing, frozen design choice, not something this ADR changes), which imports every manager including `DoctorManager`. When `heimei.cli.doctor` was reached before `heimei.core` got a "clean" first entry (an accident of `main.py`'s existing import order), this produced a real `ImportError: cannot import name ... from partially initialized module`. Fixed entirely within `heimei.doctor` — no frozen file was touched: type-hint-only uses of `InventoryService`/`RuntimeContext` now use `from __future__ import annotations` plus `TYPE_CHECKING`-guarded imports (never evaluated at runtime); `DoctorManager`'s genuine runtime dependencies (`HealthState`, `HealthStatus`, `InventoryService`, `LoggingService`) are imported locally, inside its methods, which is always safe since nothing can call a Manager's lifecycle methods before the whole module graph has finished loading. This makes `heimei.doctor` robust regardless of import order elsewhere, rather than relying on `main.py`'s current order by luck.
2. **A real false-positive found by manually running the finished CLI**: the Storage check flagged every snap package's read-only squashfs mount (e.g. `/snap/firefox/8107`) as `CRITICAL` — these always report ~0% free by design (fixed-size, read-only images), not because anything is wrong. `StorageMount` (Inventory, frozen) carries no filesystem-type or read-only flag to detect this precisely, and adding one would mean changing frozen Inventory — out of scope for this ADR. Fixed with a path-based filter (`path.startswith("/snap/")`) inside `checks/storage.py` only. This is deliberately narrower than a general "skip read-only filesystems" rule would be; a more precise fix is named in Future Work.
3. **`Application` and `main.py` needed one more change each**, both the same *kind* of sanctioned exception already used for Logging and Inventory: `Application.__init__` now also does `self.runtime.register(DoctorManager())`. Separately, `main.py`'s top-level callback now sets `ctx.obj = application` — without this, no CLI subcommand had any way to reach the already-constructed `Application`'s `ServiceContainer` at all (the existing `heimei config` commands sidestep this by using Configuration's standalone singleton, which Doctor has no equivalent of, since `DoctorService` only exists once `DoctorManager.initialize()` has run inside a real `Runtime`).

With implementation matching the refined design, this ADR is now frozen (see Stability, above).

---

## Architecture

```text
Application.__init__
    runtime.register(LoggingManager())      -- wired (ADR-0012)
    runtime.register(InventoryManager())     -- wired (ADR-0013)
    runtime.register(DoctorManager())         -- wired (this ADR, Revision v1.0)
        |
        v  (Runtime resolves order: logging, inventory before doctor)
DoctorManager
    .initialize(context)  -- log "initialized"; resolve InventoryService ONCE; construct
                              DoctorService(inventory); register all 6 built-in checks;
                              register DoctorService into context.services
    .startup()              -- no-op
    .health()                -- manager's own operational health (NOT a machine-health judgment)
    .shutdown()              -- no-op
        |
        v (context.services.register(DoctorService, service))
ServiceContainer                       -- unchanged, frozen (ADR-0011)
        |
        v (resolved via ctx.obj.services.get(DoctorService) — main.py now sets ctx.obj)
DoctorService                           -- the rule engine; owns one CheckRegistry
    .register(check: HealthCheck)         -- delegates to CheckRegistry
    .run(category=None, check=None) -> tuple[Finding, ...]
        |
        v (each registered check runs independently; one failing yields a CRITICAL Finding, not an abort)
heimei/doctor/checks/   -- each: HealthCheck (name, category, run(inventory)); no cross-imports; no OS calls
    cpu.py  memory.py  storage.py  network.py  gpu.py  docker.py
        |
        v (each check calls InventoryService methods only — never psutil/platform/GPU/docker tooling)
InventoryService                        -- unchanged, frozen (ADR-0013)
        |
        v
heimei/cli/doctor.py
    groups findings by check; prints one ✔ <name> line per clean check,
    or each non-OK finding's own icon+message; exits 1 iff any CRITICAL
```

---

## Alternatives Considered

### Option 1: No Doctor manager — health logic lives ad hoc in the CLI (status quo)

Cons: no structure, no typed findings, no reuse for a future automated monitor.

### Option 2: Fold health checks into `InventoryService` itself

Cons: conflates two concerns Inventory's own ADR (0013, section 6) ruled out for itself ("Inventory never performs health analysis"); every new judgment call would require touching frozen `InventoryService`.

### Option 3: Auto-discovery of checks (drop a file in `checks/`, it's picked up automatically)

Cons: introduces magic no other part of Heimei uses — `ServiceContainer` explicitly forbids "auto-discovery of what to register" (ADR-0011). Explicit registration costs one line per check and keeps every check's existence visible in code.

### Option 4 (rejected on review): `HealthCheck.run(services: ServiceContainer)` — the pre-refinement design

Pros: a future second data source needs no signature change.

Cons: the specific concern raised on review — checks should be independent of the platform (Runtime/Container) they run under, not just independent of each other. A check holding a `ServiceContainer` could resolve *anything*, which is more power than "consumes only the inventory data it needs" calls for.

### Option 5 (accepted): `DoctorManager`/`DoctorService`/`CheckRegistry` split; `HealthCheck.run(inventory: InventoryService)`; `Category` on every `Finding`; explicit registration; engine has no business logic; a failing check yields a Finding, not an aborted run

Pros: third validation of the one-file-per-concern extensibility pattern; checks are maximally decoupled from infrastructure, not just from each other; `Category` gives filtering (`run(category=...)`) real value instead of being purely descriptive.

Cons: adding a second data source to `HealthCheck` later is a real signature change, not a one-line addition inside an unaffected check — accepted deliberately (Decision, section 1).

---

## Consequences

Positive

- `heimei/cli/doctor.py` now does real work, migrated fully from its "under development" placeholder.
- A future automated health monitor could call the exact same `DoctorService.run()` a CLI command does.
- One broken check can't take down the diagnostic run.
- Validates the Manager/Service split and the one-file-per-concern pattern a third time, and (per Revision v1.0) surfaced and fixed a real circular-import fragility in the process, entirely within new code.
- `Category` filtering means a future `heimei doctor --category storage` (not built, but trivial) costs nothing architecturally.

Negative

- Explicit registration means every new check costs a one-line addition to `DoctorManager.initialize()`, in addition to the check file itself.
- The Inventory-vs-Configuration reconciliation both ADR-0008 and ADR-0013 anticipated as Doctor's job is *not* delivered here.
- The Storage check's snap-mount filter (Revision v1.0) is a narrower, path-based fix for a specific observed false positive, not a general "ignore read-only filesystems" rule — a real limitation, named in Future Work.

Trade-offs

- Converting a failing check into a Finding trades strict consistency with Core Runtime's error philosophy for fault isolation at a layer where that trade makes sense.
- `HealthCheck.run(inventory)` accepting exactly one, fixed type is less flexible than the rejected `ServiceContainer` design — accepted because the review's stated goal (platform independence) outweighs that flexibility for now.

---

## Future Work

- **Inventory-vs-Configuration reconciliation** (`Category.CONFIGURATION`) — comparing `inventory.machine()` against `configuration.get("machine", MachineManifest)` and reporting drift. Named by ADR-0008 and ADR-0013 as Doctor's eventual job; not built here.
- A more general fix for the Storage check's mount filtering (e.g. skipping by filesystem type or read-only flag) — would require adding a field to Inventory's frozen `StorageMount`, which needs its own separate approval, not assumed here.
- Checks using `Category.SOFTWARE` — installed-software discovery/health, not designed here.
- More checks as real needs appear (CPU load if Inventory ever exposes it, network topology detail) — a new file under `checks/` plus one registration line in `DoctorManager.initialize()`.
- Whether `DoctorManager` needs its own manifest (configurable thresholds, e.g. "warn below 15% free disk," as data instead of hardcoded constants) — no manifest proposed.
- Whether findings should ever be persisted (a history of Doctor runs over time) — not designed; `Finding.evaluated_at` supports single-run freshness, not a time series.
- `--category`/`--check` CLI flags mirroring `DoctorService.run()`'s own filtering — not built; the CLI only runs everything today.
- Unifying `heimei/cli/config.py`'s standalone-singleton pattern with `heimei/cli/doctor.py`'s new `ctx.obj`-based pattern — the two CLI modules now resolve their services differently, for historical reasons (Configuration is usable standalone; Doctor genuinely needs the Runtime to have registered its checks). Not unified here.

---

## References

Related ADRs: ADR-0008 (Configuration Manager — the reconciliation this ADR defers), ADR-0011 (Core Runtime — the frozen Manager/Service/Runtime contract and "no business logic"/"no auto-discovery" principles this proposal follows, and the "a failure propagates" principle it narrowly departs from), ADR-0012 (Logging Manager — the Manager+Service split and one-file-per-concern pattern this proposal follows a second time), ADR-0013 (Inventory Manager — the sole data source this is built on top of, and the `HealthState`-vs-machine-health distinction extended to `Severity`).

Documentation: `Projects/Heimei/src/heimei/doctor/` (implementation), `Projects/Heimei/tests/test_doctor_*.py` and `test_cli_doctor.py` (tests), `Projects/Heimei/src/heimei/cli/doctor.py` (the CLI, no longer a placeholder).
