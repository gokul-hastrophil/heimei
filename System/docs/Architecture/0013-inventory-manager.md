# ADR-0013: Inventory Manager

Status: Accepted

Version: 1.1 (wired into Application 2026-08-05 — see Decision, "Revision (v1.1)")

Date: 2026-08-05

Author: Gokul

Stability: Frozen. Implemented in `heimei.inventory` exactly as designed, without modifying `heimei.config`, `heimei.core`, or `heimei.logging`. Treat as stable infrastructure, per the same discipline applied to ADR-0008, ADR-0011, and ADR-0012 — extend by adding a collector or a new consumer, not by changing `InventoryService`'s eight methods, `InventoryManager`'s lifecycle, or `InventoryRecord`.

---

## Context

Three managers now exist on the frozen `heimei.core` Runtime/ServiceContainer contract: Configuration (ADR-0008, static/curated manifest data), Logging (ADR-0012, structured output), and nothing yet owns *live machine state* — CPU, memory, disk, OS/platform facts. Today that gap is filled ad hoc: `heimei/cli/info.py` calls `platform.system()`, `platform.release()`, `platform.machine()`, and `platform.python_version()` directly. `psutil` has been a fixed project dependency (`pyproject.toml`, since before Configuration existed) with no consumer at all — the same shape `loguru` was in before Logging Manager.

**Naming disambiguation, up front:** this ADR's "Inventory Manager" is unrelated to the existing `State/Inventory/` directory (`State/Inventory/project-inventory.md` — a curated report about what *code projects* exist in this workspace). "Inventory" here means live *machine* state: what this specific host's CPU, memory, disk, GPU, and OS look like right now. The two concepts happen to share a word; they don't share data or code.

Two existing stub packages are natural future *consumers* of this data, not the thing being proposed: `heimei/status/` (presumably `heimei status` would show live machine state) and `heimei/doctor/` (presumably health checks would compare live state against expectations). Neither is designed here.

This is the second revision. v0.1 modeled `InventoryService` as a generic `get(category, model, force=)`. v0.2 replaced that with nine named methods backed by independent collectors, and surfaced five open judgment calls as Review Notes rather than deciding them unilaterally. This revision (v0.3) resolves those judgment calls with explicit decisions, and freezes the design. See "Revision (v0.3)" below.

---

## Problem Statement

Heimei needs one place that owns querying the operating system for machine state, so that:

- **No CLI command, manager, or subsystem queries the OS directly** if Inventory already exposes that information — the same principle already applied to YAML (Configuration) and to `loguru`/stdout (Logging), now applied to `psutil`/`platform`/GPU tooling/`docker`.
- Machine state is typed and structured, not ad hoc `platform.system()` calls scattered across CLI commands and future managers.
- Callers can ask for a specific, named fact (`inventory.memory()`) and get a strongly typed answer, without knowing anything about strings, categories, or a generic lookup mechanism.
- Genuinely volatile facts can be queried fresh on demand, while caching stays entirely internal — no caller ever needs to know *how* freshness is achieved, only whether they asked for it.
- Optional hardware or software that simply isn't present on a given machine (no GPU, no Docker) is reported as a normal fact, never an exception — Inventory only reports; it never fails because something is absent.
- Every returned snapshot carries enough metadata (when it was collected, how, by what) that a consumer — Doctor, Status, or a future monitor — can judge for itself whether the data is stale, without Inventory having an opinion about what "stale" means for their use case.
- The design plugs into the frozen `Manager`/`ServiceContainer`/`Runtime` contract (ADR-0011) and, ideally, validates it with the *first real* (non-test) manager-to-manager dependency edge, since Inventory has an obvious, genuine reason to depend on Logging.

---

## Decision

Introduce `heimei.inventory` as a new, independent package — a peer of `heimei.config` and `heimei.logging`, not a submodule of `heimei.core`. **This requires zero changes to `heimei.core`, `heimei.config`, or `heimei.logging`.**

### 1. `InventoryManager` and `InventoryService` — the same Manager/Service split Logging Manager validated

```python
class InventoryManager:
    name = "inventory"
    dependencies: tuple[str, ...] = ("logging",)

    def initialize(self, context: RuntimeContext) -> None: ...
    def startup(self) -> None: ...
    def health(self) -> HealthStatus: ...
    def shutdown(self) -> None: ...

    service: InventoryService   # registered into the ServiceContainer during initialize()
```

`dependencies = ("logging",)`: Inventory logs its own diagnostic events the same way every manager must (never `print()`), and this is the first *real* dependency edge between two actual managers — until now only test doubles exercised the Runtime's dependency-ordering. `initialize()` registers `InventoryService` into the Container; `startup()` is a no-op — querying the OS has no connection or file handle to open, unlike Logging's file sink.

`InventoryManager.health()` is about the *manager's own* operational health (per the Manager contract every manager implements) — e.g. `UNHEALTHY` if the service failed to construct. It is **not** an assessment of whether the *machine* is healthy (low disk, high memory pressure) — that question belongs entirely to a future Doctor manager (see Scope, below). The two meanings of "health" sit at different layers and must not be conflated in implementation or in docs.

**Directionality (explicit, per this revision): Inventory is consumed; it never consumes.** Status, Doctor, and any future manager that wants machine state calls into `InventoryService`. Inventory calls into nothing except Logging (for its own diagnostic output, an infrastructure dependency every manager has, not a "consumer of Inventory's data" relationship). Inventory must never import or depend on Status, Doctor, or any other data-consuming manager, now or later — consumption flows strictly one way.

### 2. `InventoryService` — an expressive façade over eight named methods

```python
class InventoryService:
    def machine(self) -> MachineSnapshot: ...
    def cpu(self) -> CpuSnapshot: ...
    def python(self) -> PythonSnapshot: ...
    def memory(self, *, refresh: bool = False) -> MemorySnapshot: ...
    def storage(self, *, refresh: bool = False) -> StorageSnapshot: ...
    def network(self, *, refresh: bool = False) -> NetworkSnapshot: ...
    def gpu(self, *, refresh: bool = False) -> GpuSnapshot: ...
    def docker(self, *, refresh: bool = False) -> DockerSnapshot: ...
```

Eight named methods (`models()` removed — see section 3), each returning a strongly typed model. No `get(category, model)`, no string keys, nothing generic in the public surface.

**`refresh` exposure is now a closed decision, not a judgment call:**

- **No `refresh` parameter:** `machine()`, `cpu()`, `python()`. Collected once, cached for the `InventoryService` instance's lifetime, with no way to invalidate — there is nothing to invalidate them for.
- **`refresh: bool = False` exposed:** `memory()`, `storage()`, `network()`, `docker()`, `gpu()`.

This resolves v0.2's Review Note 1 in favor of the narrower reading: `cpu()` joins `machine()`/`python()` as permanently cached, not the wider "comparably volatile" set v0.2 had proposed. A `CpuSnapshot` under this decision reports structural facts (core counts, max frequency) that don't need refreshing, not a live usage percentage — see section 4.

`InventoryService` is a **façade**: it knows about all eight collectors (below) and decides, per call, whether to return a cached value or collect a fresh one. Collectors know none of this — they don't cache, don't know about `InventoryService`, and don't know about each other.

### 3. `models()` is removed from this ADR — deferred entirely to Future Work

v0.2 included a `models()` method and flagged it as the least-defined of the nine, dependent on decisions ADR-0005 (Model Router, still an unfilled template) hasn't made. This revision removes it outright rather than shipping a speculative shape: no `ModelsSnapshot`, no `ModelEntry`, no `collectors/models.py`. It belongs after a Model Registry and Model Router exist to say what "a model" actually means for Heimei's purposes — Inventory does not speculate about that architecture. `InventoryService` therefore has eight methods, not nine, and `heimei/inventory/collectors/` has eight files, not nine.

### 4. Collectors — one file, one responsibility, no cross-awareness, platform-specific by design

```
heimei/inventory/collectors/
    machine.py    -- MachineSnapshot, collect()
    cpu.py          -- CpuSnapshot, collect()
    python.py         -- PythonSnapshot, collect()
    memory.py            -- MemorySnapshot, collect()
    storage.py             -- StorageSnapshot (+ StorageMount), collect()
    network.py               -- NetworkSnapshot (+ NetworkInterface), collect()
    gpu.py                     -- GpuSnapshot (+ GpuDevice), collect()
    docker.py                    -- DockerSnapshot, collect()
```

Each module exposes exactly one function, `collect() -> SomeSnapshot`, taking no arguments and knowing nothing about caching, the Container, the Runtime, or any other collector. Each collector's Snapshot model(s) live in the *same file* as its `collect()` function, not in a shared models file — changing one collector's shape never touches a file any other collector also depends on.

The one thing every collector shares is a metadata base class:

```python
# heimei/inventory/record.py
class InventoryRecord(BaseModel):
    collected_at: datetime
    source: str              # which mechanism produced this, e.g. "psutil", "pynvml", "nvidia-smi", "lspci", "none"
    collector_version: str   # this collector's own schema/logic version, e.g. "1.0"
```

Every Snapshot model subclasses `InventoryRecord`. Depending on this shared base is not the kind of cross-awareness "collectors never know about each other" forbids — it mirrors how every `Manager` implementation depends on the shared `Manager` protocol without depending on other managers.

**Extension point: collectors are platform-specific implementations behind a stable contract.** `InventoryService` and every consumer only ever call `collect()` by import path — they never inspect *how* a collector gets its answer. `psutil` already abstracts most of the OS difference for `cpu`/`memory`/`storage`/`network`/`machine`/`python`, so those collectors need no explicit per-platform branching today. `gpu` and `docker` (section 5) already degrade gracefully across platforms *by construction*: each fallback layer's own failure mode (`ImportError`, `FileNotFoundError` from a missing binary) signals "not applicable here" and moves to the next layer, so the same `collect()` function behaves correctly on Linux, macOS, or Windows without `platform.system()` branches. If a collector ever needs genuinely different logic per OS (not just "this tool isn't installed here"), the contract that must be preserved is only `collect() -> SomeSnapshot` with no arguments — internally, that could become `collectors/gpu/linux.py` / `collectors/gpu/macos.py` / `collectors/gpu/windows.py` behind a single dispatching `collectors/gpu/__init__.py`, or a single file with an internal `platform.system()` branch. Either way, `InventoryService` does not change. No such split is built now — Heimei's current target machine is Linux (`System/manifest/machine.yaml`), and building unused macOS/Windows stubs today would be exactly the speculative design this review was asked to avoid.

`heimei.inventory.collectors` (and nowhere else in Heimei) is allowed to import `psutil`, `pynvml`, call `platform.*`, or shell out to `nvidia-smi`/`lspci`/`docker` — the same rule Configuration applies to `yaml` and Logging applies to `loguru`.

### 5. GPU and Docker — layered discovery, never an exception for absence

Neither `psutil` nor any current dependency covers GPU or Docker. Both collectors try progressively less-detailed mechanisms in order and fall through on any failure of a given layer — an unavailable library, a missing binary, a daemon that isn't running are all just reasons to try the next layer, never reasons to raise:

**`gpu()`:**
1. `pynvml` (if importable and successfully initializes) — richest detail: device name, total memory.
2. `nvidia-smi` (if the binary is on `PATH` and runs successfully) — good detail via CSV parsing, no Python dependency needed.
3. `lspci` (if the binary is on `PATH` and runs successfully; Linux-only in practice) — detects *any* GPU vendor (not just NVIDIA) by scanning for VGA/3D controller entries, but with no memory detail.
4. None of the above worked, or all of them found zero devices → `available=False`, `devices=()`.

A layer that runs but finds nothing (e.g. `pynvml` works but reports zero NVIDIA devices) does **not** stop the chain — a non-NVIDIA GPU would be invisible to `pynvml`/`nvidia-smi` but visible to `lspci`, so an empty result must still fall through. Only a layer that cannot run at all (import fails, binary missing, command errors) is skipped without being "the answer."

**`docker()`:**
1. Docker Engine API (the `docker` Python SDK, if importable and able to connect to a running daemon).
2. `docker` CLI (if the binary is on `PATH` and `docker version` succeeds — this also naturally reports unavailable if the binary exists but the daemon isn't running, since the command itself fails in that case).
3. Neither worked → `available=False`, `version=None`.

Neither `pynvml` nor the `docker` Python SDK are added as project dependencies — both are used only if already present in the environment (a plain `try: import pynvml except ImportError:` at call time), matching "if available" literally and keeping Heimei installable without either.

```python
class GpuDevice(BaseModel):
    name: str
    memory_total_bytes: int | None = None

class GpuSnapshot(InventoryRecord):
    available: bool
    devices: tuple[GpuDevice, ...]

class DockerSnapshot(InventoryRecord):
    available: bool
    version: str | None = None
```

This means a caller never needs to wrap `inventory.gpu()`/`inventory.docker()` in a `try/except` just to handle the common case of the resource not existing — checking `.available` is enough, and this holds regardless of *why* it's unavailable (no hardware, no software installed, or installed-but-not-running all collapse to the same `available=False`).

### 6. Scope

Inventory is strictly read-only and observational:

- It **never changes system state** — no writes, no service management, no installs.
- It **never reconciles configuration** — comparing live state (this ADR) against declared state (`MachineManifest`, ADR-0008) is a different operation, deliberately not built here (see section 7).
- It **never performs health analysis** — "is 2GB of free disk space a problem" is a judgment call Inventory does not make; it only reports "14GB total, 2GB free."
- It **never performs repairs** — there is no write path at all, so this follows from the first point, but is worth stating on its own since "repair" is a natural next question once "diagnose" exists.

All four belong to future managers (Doctor, most likely) built *on top of* `InventoryService`, not inside it.

### 7. Relationship to Configuration's `MachineManifest` — still deliberately not reconciled

`System/manifest/machine.yaml` (ADR-0008) already describes this machine — but as static, user-curated facts (hostname, a hand-entered "RTX3050" GPU string, a `tailscale: true` flag) that change only when someone edits the file. `InventoryService.machine()` describes the same machine *as discovered right now* by the OS — and the shared method name (`machine()`, `MachineManifest`) is intentional, not a naming accident: anyone implementing or reading this code should expect both to exist and expect them to be *allowed to disagree*. Reconciling them is Doctor's future job, not Inventory's.

### 8. Enforcement is convention, same as the other two managers

Nothing technically prevents a future subsystem from calling `psutil`, `platform`, or `docker` directly instead of going through Inventory — exactly as nothing technically stops a subsystem from calling `yaml.safe_load` instead of Configuration, or `loguru` instead of Logging. The rule is a documented convention enforced by review, not a runtime sandbox.

---

### Revision (v0.2, same day — design refinement)

Replaced the v0.1 generic `InventoryService.get(category, model, force=)` with nine named methods backed by independent collectors (`heimei/inventory/collectors/*.py`), replaced `force=True` with `refresh=True`, and added `InventoryRecord` as a shared metadata base. Surfaced five open judgment calls as Review Notes rather than deciding them: which methods get `refresh`, how `gpu()`/`docker()` would actually be implemented, `models()`'s unclear scope, and two naming-friction observations.

### Revision (v0.3, same day — approved with decisions; design frozen)

Five decisions resolve v0.2's Review Notes and freeze the design:

1. **`refresh` exposure settled** on the narrower reading: `memory()`, `storage()`, `network()`, `docker()`, `gpu()` get it; `machine()`, `cpu()`, `python()` do not. v0.2 had speculatively extended it to `cpu()` (and, before removal, `models()`) — this revision reverses that for `cpu()`; see section 2.
2. **GPU and Docker discovery mechanisms are now specified**, not left as an implementation-time gap: the three-layer GPU chain (`pynvml` → `nvidia-smi` → `lspci` → unavailable) and two-layer Docker chain (Engine API → CLI → unavailable), both required to degrade to `available=False` rather than raise. This resolves v0.2's Review Note 2.
3. **`models()` is removed entirely**, not merely deferred with a placeholder shape. v0.2 had included a best-effort `ModelsSnapshot`/`ModelEntry` sketch and flagged it as low-confidence; this revision concludes that sketching it at all was premature and removes it, moving the whole method to Future Work pending a Model Registry and Model Router. This resolves v0.2's Review Notes 3 and 4 (the `collectors/models.py` naming friction disappears along with the file).
4. **Directionality made explicit**: Inventory is consumed by Status/Doctor/future managers and never consumes them — stated as its own rule (section 1) rather than left implicit in the Manager/Service split.
5. **Collectors are documented as platform-specific implementations behind a stable `collect()` contract** (section 4), so future Linux/macOS/Windows-specific logic can be swapped in without `InventoryService` changing. No platform-specific files are built now; the extension point is documented, not pre-built.

Review Note 5 (the `machine()`/`MachineManifest` naming overlap) was reviewed and intentionally left as-is — section 7 already treats it as a feature, not a defect, and no further action was requested.

With these decisions, ADR-0013's design was frozen; implementation followed immediately.

### Revision (v1.0, same day — implemented and frozen)

Implementation matched the v0.3 design exactly: `heimei.inventory` (`record.py`, `service.py`, `manager.py`, `collectors/{machine,cpu,python,memory,storage,network,gpu,docker}.py`) required zero changes to `heimei.config`, `heimei.core`, or `heimei.logging` — confirmed by never touching any of their source files during implementation. `InventoryManager.initialize()` resolves `LoggingService` from the Container and logs its own initialization, giving the `dependencies=("logging",)` edge a real exercise rather than a declared-but-unused dependency. Verified end-to-end against the real machine: `gpu()` correctly found the actual RTX 3050 via the `nvidia-smi` layer (`pynvml` not installed, so layer 1 fell through as designed), and `docker()` found a real running daemon via the CLI layer (`docker` Python SDK not installed). 157 tests pass, ruff/mypy clean.

One implementation-time addition beyond the frozen design, needed for type-checking rather than a design change: `types-psutil` added as a dev-only type-stub dependency (mirroring `types-PyYAML` from ADR-0008) — no runtime dependency changed.

**Not done at v1.0, by design, per this ADR's own Future Work:** `InventoryManager` was not yet wired into `Application`; `heimei/cli/info.py` was not migrated off direct `platform.*` calls; no `heimei inventory show` CLI command was added.

### Revision (v1.1, same day — wired into `Application`)

`Application.__init__` (`heimei/core/application.py`) now does `self.runtime.register(InventoryManager())` immediately after registering `LoggingManager()`, mirroring exactly how Logging was wired in (ADR-0012). This is the same sanctioned exception as before: the edit only calls the existing, frozen `Runtime.register()` — it changes no behavior of `Runtime`, `ServiceContainer`, `Manager`, `RuntimeContext`, or `ConfigurationService`/`LoggingManager` themselves, confirmed by not touching any of their source files. Registration order in `Application` (Configuration service → Logging manager → Inventory manager → `Runtime.startup()`) matches the order the Runtime's dependency-based sort already derives from `InventoryManager.dependencies = ("logging",)` — the explicit registration order is documentation for a human reading `Application`, not something the Runtime needed to be told.

`heimei/cli/info.py`'s migration and a `heimei inventory show` command remain open, unauthorized by this revision — only the Application wiring was in scope.

With Application wiring complete, this ADR remains frozen as stable infrastructure (see Stability, above).

---

## Architecture

```text
Application.__init__
    runtime.register(LoggingManager())      -- wired (ADR-0012)
    runtime.register(InventoryManager())     -- wired (this ADR, Revision v1.1)
        |
        v  (Runtime resolves dependency order: logging before inventory)
InventoryManager
    .initialize(context)  -- log "initialized" via LoggingService; register InventoryService
    .startup()              -- no-op
    .health()                -- manager's own operational health (NOT machine health — see section 1)
    .shutdown()              -- no-op
        |
        v (context.services.register(InventoryService, self.service))
ServiceContainer                       -- unchanged, frozen (ADR-0011)
        |
        v (resolved by any other code via context.services.get(InventoryService); NEVER the reverse)
InventoryService                        -- façade; caching is a private implementation detail
    .machine()   .cpu()   .python()                        -- no refresh; cached forever
    .memory(refresh=)   .storage(refresh=)   .network(refresh=)
    .gpu(refresh=)       .docker(refresh=)
        |
        v (each method delegates to exactly one collector on a cache miss / refresh=True)
heimei/inventory/collectors/   -- each: collect() -> SomeSnapshot; own model(s); no cross-imports
    machine.py  cpu.py  python.py  memory.py  storage.py  network.py  gpu.py  docker.py
        |                                                        |            |
        v (psutil / platform.* / socket)          pynvml -> nvidia-smi -> lspci -> unavailable
        |                                          docker-engine-api -> docker-cli -> unavailable
        v
Consumers (heimei/cli/info.py migrates to this; future heimei/status/, heimei/doctor/)
    each: context.services.get(InventoryService).memory()
    never: platform.system() / psutil.* / docker CLI / nvidia-smi directly
```

---

## Alternatives Considered

### Option 1: No Inventory Manager — subsystems query `platform`/`psutil`/`docker` directly (status quo)

Pros

- Zero new code; `cli/info.py` already works this way.

Cons

- Directly contradicts the stated requirement; every future manager wanting machine state reimplements its own OS queries with no shared caching or typing.

### Option 2: Fold machine-state queries into Configuration's `MachineManifest`

Pros

- One fewer manager; reuses an already-frozen, well-understood pattern.

Cons

- Conflates two fundamentally different kinds of data: user-curated, rarely-changing declaration versus live, constantly-changing OS discovery.

### Option 3 (rejected): `InventoryService.get(category, model, *, force=False)` — the v0.1 design

Cons

- Treats Inventory like a second Configuration Manager despite having a small, fixed, known category set. No IDE autocomplete or static typing on a category string. The specific concern raised on review: "Inventory is NOT a generic configuration system."

### Option 4 (rejected): Include a speculative `models()` method with a best-effort shape — the v0.2 design

Pros

- Complete parity with the originally requested nine-method list.

Cons

- What counts as "a model" depends on Model Registry/Model Router decisions that don't exist yet (ADR-0005 is still an unfilled template). Shipping a guessed shape now risks building against the wrong thing and reworking it once those decisions land — the specific concern raised on this review: "Do not speculate about future model architecture."

### Option 5 (accepted): Eight named `InventoryService` methods, refresh limited to the five genuinely volatile ones, layered GPU/Docker discovery, `models()` deferred entirely

Pros

- Every category is statically typed and discoverable.
- Collectors are independently testable, independently replaceable, and structurally guaranteed not to couple to each other.
- GPU/Docker absence — for any reason — is a normal, typed fact, never a raised exception.
- Removing `models()` avoids building on top of an architecture decision (Model Registry/Router) that hasn't been made.

Cons

- Eight fixed methods instead of one generic one means adding a future category is a new method plus a new collector, not "just a new string" — the correct trade for a category set that's small and known rather than open-ended.

---

## Consequences

Positive

- `cli/info.py`'s direct `platform.*` calls have a concrete, already-identified migration target.
- `InventoryService`'s API is self-documenting.
- Collectors are trivially unit-testable in isolation and trivially replaceable, including per-platform in the future (section 4).
- GPU/Docker absence is handled uniformly regardless of cause (no hardware, no software, daemon not running) — one `available` check covers all of them.
- Every Snapshot's `collected_at`/`source`/`collector_version` gives Doctor, Status, and any future monitor a freshness signal for free.
- Validates Core Runtime's dependency ordering with a real production dependency edge (`inventory` → `logging`).
- Not shipping `models()` avoids a rework once Model Registry/Router decisions land.

Negative

- Eight methods (plus their Snapshot models, plus their collectors) is measurably more code than one generic `get()` — deliberate, per this ADR's own instruction to avoid modeling Inventory as a second Configuration Manager.
- The GPU/Docker fallback chains are the most complex code in this ADR — three and two layers respectively, each with its own failure mode to handle correctly (see section 5's "a layer that runs but finds nothing must still fall through" rule, which is easy to get subtly wrong).
- `refresh=True` correctness is entirely caller-driven, the same property `force=True` had in v0.1.

Trade-offs

- Fixing `refresh` exposure to a specific five methods (rather than "all volatile-seeming ones") is simpler to reason about but means a future category's volatility must be judged explicitly when it's added, not inferred from a general rule.
- Co-locating each collector's model with its `collect()` function means there's no single file listing every Snapshot's fields at a glance — traded for materially stronger collector isolation.

---

## Future Work

- **`models()`** — the removed method. Belongs after a Model Registry and Model Router exist to define what "a model" means for Heimei. Not designed here at all, per explicit instruction.
- Migrating `heimei/cli/info.py` off direct `platform.*` calls.
- `heimei/status/` and/or `heimei/doctor/` becoming real consumers of `InventoryService` — `InventoryManager` is now wired into `Application` (Revision v1.1), so `context.services.get(InventoryService)` is live in the real CLI process for any future consumer.
- A health-check that compares live Inventory state (`machine()`) against declared `MachineManifest` state and reports drift — `heimei/doctor/` territory, not Inventory's.
- Additional collectors as real needs appear (running processes, more detailed network topology) — a new file under `collectors/` and a new `InventoryService` method; no change to the existing eight.
- Platform-specific collector implementations (Linux/macOS/Windows) if a real cross-platform need appears — the extension point is documented (section 4), not built.
- Whether `InventoryManager` needs its own manifest — no manifest is proposed; only add one if a real configuration need appears.
- A `heimei inventory show` CLI command, mirroring `heimei config show`.

---

## References

Related ADRs: ADR-0008 (Configuration Manager — `MachineManifest`, and the `get(name, model)` pattern this design explicitly does not reuse for Inventory's public API), ADR-0011 (Core Runtime — the frozen Manager/Service/Runtime contract this proposal builds on without modifying), ADR-0012 (Logging Manager — the Manager+Service split this proposal follows, and the dependency this proposal's manager declares).

Documentation: `Knowledge/Documentation/Glossary.md` (`State/Inventory/` — the unrelated existing concept disambiguated in Context), `Projects/Heimei/src/heimei/cli/info.py` (the concrete existing violation this would fix), `Projects/Heimei/pyproject.toml` (`psutil`, already a fixed, unused dependency; `pynvml` and the `docker` SDK are used only if already present in the environment, never added as project dependencies — section 5).
