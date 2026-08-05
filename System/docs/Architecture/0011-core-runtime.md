# ADR-0011: Core Runtime

Status: Accepted

Version: 1.0 (implemented and frozen 2026-08-05 — see Decision, "Revision (v1.0)")

Date: 2026-08-05

Author: Gokul

Stability: Frozen. Implemented exactly as designed in `heimei.core` (Application, ServiceContainer, Manager, RuntimeContext, Runtime) and approved. Treat as stable infrastructure — no new capabilities, no premature optimization. The next changes to `heimei.core` should come only from a demonstrated need surfaced by implementing a later manager (Memory, Model Router, ...), never from speculation. A later manager needing something from the Runtime should first ask "can this be done entirely inside my own `Manager` implementation?" before asking "does `Runtime`/`ServiceContainer` need to change?"

---

## Context

Configuration Manager (ADR-0008) is Heimei's first manager and is now frozen. The workspace already anticipates several more: a plugin system (ADR-0003, unfilled), a memory manager (ADR-0004, unfilled), a model router (ADR-0005, unfilled), an agent system (ADR-0006, unfilled), security (ADR-0007, unfilled), and an event system (ADR-0009, unfilled). The root `Core/` directory (`events/`, `plugins/`, `registry/`, `runtime/`, `scheduler/`) and its code counterpart `heimei.core` already exist as empty placeholders for exactly this orchestration role (see `Knowledge/Documentation/Glossary.md`, "Core").

Today nothing fills that role. `src/heimei/main.py` imports each CLI Typer app directly and wires it with `app.add_typer(...)`. That works for four thin CLI stubs plus Configuration, but it has no concept of a manager's lifecycle, no shared way for one manager to reach another (or reach Configuration) without an ad hoc import, and no single place to ask "what's running."

---

## Problem Statement

Before more managers are built, Heimei needs one orchestration layer that:

- Gives every manager a consistent way to initialize, start, be health-checked, and shut down.
- Orders that lifecycle correctly as managers gain real dependencies on each other, without relying on whoever assembles the Runtime to get manual ordering right.
- Gives managers a way to depend on Configuration (and, later, each other) without ad hoc imports.
- Provides a single place to answer "what's registered" instead of that being implicit in `main.py`.
- Leaves room for a plugin system, scheduler, and event bus (the other reserved `Core/` subdirectories) to attach later without a redesign.
- Does not impose more machinery than a single-user, single-process system currently needs — the same minimalism principle applied to Configuration, including after its own freeze review found and removed unused surface.

---

## Decision

Introduce `heimei.core` as the Core Runtime, built from four pieces with strictly non-overlapping responsibilities:

- **`Runtime`** derives order and drives lifecycle. It contains **no business logic of any kind** — see "Runtime has no business logic" below.
- **`ServiceContainer`** owns shared service instances and answers `register`/`get`/`has`. Nothing more.
- **`Manager`** protocol — the four-method lifecycle every manager implements, plus declared `dependencies`.
- **`RuntimeContext`** — the single object carrying a manager's access to the `ServiceContainer`.

### 1. Manager lifecycle: `initialize()` → `startup()` → `health()` → `shutdown()`

```python
class Manager(Protocol):
    name: str
    dependencies: tuple[str, ...]   # names of other Managers this one depends on

    def initialize(self, context: RuntimeContext) -> None: ...
    def startup(self) -> None: ...
    def health(self) -> HealthStatus: ...
    def shutdown(self) -> None: ...
```

Two phases exist before a manager is "up," not one, and they mean different things:

- **`initialize(context)`** — wiring only. A manager resolves what it depends on via `context.services.get(...)` and registers whatever it exposes via `context.services.register(...)`. No I/O, no background work, no side effects beyond wiring.
- **`startup()`** — activation. Only after *every* manager has been initialized does *any* manager begin active operation (open connections, start loops, etc.). Takes no arguments — everything the manager needs was already resolved in `initialize()`.

The Runtime therefore runs two full passes in dependency order: `initialize()` on every manager, then `startup()` on every manager. This removes the ordering hazard where manager B's `initialize()` wants to resolve something manager A only registers partway through A's own startup — wiring is guaranteed complete, workspace-wide, before anything becomes active. It also answers the open question left in v0.2 about *when* a manager should register itself: always in `initialize()`, never in `startup()`.

`shutdown()` reverses `startup()` only (there is no "deinitialize" step) — the Runtime calls `shutdown()` on every manager in reverse dependency order.

`health()` takes no arguments and can be called at any time after `initialize()`, independent of the startup/shutdown cycle — it's how the Runtime's registry view and a future `heimei core status` command inspect a running manager.

### 2. Dependency-based ordering replaces manual registration order

Each manager declares `dependencies: tuple[str, ...]` — the `name`s of other managers that must be initialized and started before it. The Runtime derives startup order via a topological sort over all registered managers' declared dependencies (dependencies before dependents), and shutdown order as its exact reverse. `Runtime.register(manager)` no longer implies anything about order — managers can be registered in any sequence; the Runtime computes the real order from the dependency graph before `startup()` runs.

Two failure modes are inherent to this and must produce clear errors (per the project's established standard — see ADR-0008): a manager declaring a dependency name that was never registered, and a dependency cycle. Both are detectable before any manager's `initialize()` runs, so they fail fast at startup rather than partway through.

### 3. `ServiceContainer` stays a three-method registry — nothing else

```python
class ServiceContainer:
    def register(self, service_type: type[T], instance: T) -> None: ...
    def get(self, service_type: type[T]) -> T: ...
    def has(self, service_type: type[T]) -> bool: ...
```

`has()` is the one addition since v0.2, added specifically so a manager with an optional/soft dependency can check for a service without triggering an exception via `get()` on something that legitimately might not be registered.

This is the container's entire responsibility, permanently: a flat, type-keyed store of already-constructed instances. It explicitly does **not** do any of the following, now or later without a new ADR: scoping or lifetimes (everything is a process-wide singleton once registered), factories or lazy construction, constructor/attribute auto-injection, child or hierarchical containers, or auto-discovery of what to register. Registration is always an explicit call, always made by the manager that owns the instance, always from inside that manager's own `initialize()`.

### 4. `HealthStatus` — a common interface, defined now, empty of implementation

```python
class HealthState(Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"

@dataclass(frozen=True)
class HealthStatus:
    state: HealthState
    detail: str | None = None
```

Every manager's `health()` returns exactly this shape — three states, one optional free-text detail. What follows is deliberately undefined here and left to each manager: what counts as "degraded" versus "unhealthy" for that manager, how `detail` is worded, whether a check is cheap enough to run synchronously or should be cached. Only the interface is frozen, not any manager's judgment of its own health.

### 5. `RuntimeContext` carries exactly one thing

```python
class RuntimeContext:
    services: ServiceContainer
```

Passed only to `initialize()`. No named attribute is ever added here for a specific service — that was the god-object shape rejected in v0.2 (see Revision history below). Everything a manager needs comes from `context.services`.

### 6. Runtime has no business logic

The Runtime's entire responsibility is: hold the set of registered managers, derive their dependency order, call each lifecycle method on each manager in the correct order, and expose a **read-only** view of the result. It must never:

- Know what a specific manager (Configuration, Memory, ...) actually does, or special-case behavior by manager name or type.
- Retry, suppress, or reinterpret a manager's failure — a failed `initialize()`/`startup()` propagates, it is not silently handled by policy living in the Runtime.
- Contain domain logic of any kind. If a piece of logic looks like it belongs in the Runtime because "it needs to run for every manager," it belongs in the `Manager` protocol (so every manager implements it) or in a service the managers share (via the Container) — never bolted onto `Runtime` itself.

`Runtime.managers` remains **read-only**: a query surface (name, resolved order, lifecycle state, live `health()`), never a mutation point. Only `Runtime.register()` changes the registered set, and only before `startup()` has run.

### Manager vs. Service (unchanged from v0.2)

These are two roles a subsystem can play, not two kinds of object. Configuration, Memory, the Model Router, and a Plugin Manager are each expected to be *both* — a Manager the Runtime drives through its lifecycle, and a Service other managers can resolve through the Container by registering themselves during `initialize()`. A few things registered in the Container (e.g. a stateless Logger wrapper) may be pure services with no lifecycle worth tracking, and so are never registered as a Manager.

### Relationship to Configuration (unchanged)

The Runtime and Container *depend on* Configuration, never the reverse. Configuration stays fully usable standalone via `get_configuration_service()` with no Runtime or Container involved, exactly as today.

---

### Revision (v0.2, same day)

The first draft (v0.1) had the Runtime own a `RuntimeContext` that directly carried `config: ConfigurationService` as a named attribute, with a comment that "(future) event_bus, scheduler" would be added the same way. Feedback on review: that makes the Runtime itself the owner of shared services, and `RuntimeContext` would grow one hardcoded attribute per service forever — precisely the `HeimeiConfig` mistake, one layer up. Revised to split ownership: the Service Container owns and resolves shared services by type; the Runtime owns only Manager lifecycle; `RuntimeContext` shrinks to a single `.services` reference. Also added `health()` to the `Manager` protocol from v1, per explicit direction.

### Revision (v0.3, same day — approved with refinements)

Five refinements applied on approval, before implementation:

1. **Lifecycle expanded** from `startup()`/`shutdown()`/`health()` to `initialize()`/`startup()`/`health()`/`shutdown()`, with `initialize()` doing wiring/registration and `startup()` doing activation, run as two full passes across all managers. This also resolved v0.2's open question about exactly when a manager should call `ServiceContainer.register()` — always in `initialize()`.
2. **Manual registration order replaced with dependency-based ordering.** Managers declare `dependencies: tuple[str, ...]`; the Runtime topologically sorts them for both startup (forward) and shutdown (reverse) order. This removes what v0.2 listed as its main open risk ("manual registration order is easy to get wrong") rather than merely flagging it under Future Work.
3. **`ServiceContainer` gained `has()`** (register/get/has, still exactly three methods) and an explicit, permanent disclaimer against scoping, factories, auto-wiring, or child containers — it must never grow into a dependency-injection framework.
4. **`HealthStatus` is now a frozen interface** (`HealthState` enum of healthy/degraded/unhealthy, plus optional `detail: str | None`), decided now rather than deferred to whoever writes the first manager. What counts as each state for a given manager is explicitly left unspecified.
5. **"Runtime has no business logic" is now explicit** in the Decision itself, not just implied by the Runtime/Container split — the Runtime orchestrates only; every behavioral decision lives in a Manager or a Service.

With this revision, ADR-0011's design was frozen pending implementation approval.

### Revision (v1.0, same day — implemented and frozen)

Implementation was approved and completed in `heimei.core` exactly as designed in v0.3 — no deviation. This resolved the one open question carried over from v0.2/v0.3: **Configuration is registered directly into the `ServiceContainer` at `Application.__init__` time and is not a `Manager`** — it has no real `initialize`/`startup`/`health`/`shutdown` behavior worth orchestrating, so it never enters the Runtime's lifecycle at all. `Application` simply does `services.register(ConfigurationService, get_configuration_service())` before constructing the `Runtime`. Any future manager that needs Configuration resolves it the same way every other service is resolved: `context.services.get(ConfigurationService)` inside its own `initialize()` — no dependency on a "configuration" manager name is possible or needed, since it was never registered as one.

With implementation matching the design and approved, this ADR is now frozen as stable infrastructure (see Stability, above).

---

## Architecture

```text
main.py / future bootstrap module
        |
        v
ServiceContainer                        -- register / get / has; no lifecycle, no scoping, no factories
        |
        v (given to)
Runtime(container)                      -- orchestration only, no business logic, owns no services
    .register(manager: Manager)         -- any order; ordering is derived, not declared here
    .startup()
        1. resolve dependency order      -- topological sort over declared `dependencies`
        2. initialize(context) on every manager, in that order  (wiring + self-registration)
        3. startup() on every manager, in that order             (activation)
    .shutdown()                         -- shutdown() on every manager, in REVERSE order
    .managers -> read-only view         -- (name, resolved order, lifecycle state, health())
        |
        v
RuntimeContext(services=container)      -- the ONLY thing passed to initialize(); carries .services
        |
        v
Managers (Configuration?, Memory, Agents, Model Router, Plugin Manager, ...)
    each: name, dependencies, initialize(context), startup(), health(), shutdown()
    each registers whatever it exposes via context.services.register(...) inside initialize()
```

---

## Alternatives Considered

### Option 1: No central runtime (status quo)

Pros

- Zero new code; works fine for exactly one manager.

Cons

- Doesn't scale past a handful of managers — `main.py` becomes an ad hoc pile of imports and manual wiring, no shared lifecycle, no shutdown ordering, no single place to ask "what's registered."

### Option 2: Adopt a third-party plugin/DI framework now (e.g. `pluggy`, `dependency-injector`)

Pros

- Hook, dependency-resolution, and lifecycle mechanisms already solved and battle-tested.

Cons

- Heavyweight for a single-user, single-process personal system with two managers total.
- Forecloses a simpler design before it's known whether one is needed.
- Contradicts the minimalism the project has followed so far — Configuration itself uses no framework, just a service.

### Option 3 (recommended): Small in-house `Runtime` / `ServiceContainer` / `Manager` / `RuntimeContext`, dependency-derived ordering, two-phase lifecycle, no event bus or plugin loading yet

Pros

- Matches the project's current size and philosophy — the `ServiceContainer` is a plain type-keyed dict wrapper, not a framework; the topological sort is the one piece of real algorithmic complexity, and it's small and well-understood.
- Separating "who orchestrates lifecycle" (Runtime) from "who owns shared state" (Container) means either can change independently.
- Dependency-derived ordering removes an entire class of "forgot to register in the right order" bugs before they can happen, rather than accepting them as a known risk.
- Obvious extension points — a future plugin loader is just something that produces `Manager` instances to register; a scheduler is just another thing a manager registers into the Container.

Cons

- More upfront code than manual ordering (a topological sort, cycle/missing-dependency detection) for what is currently a one-manager system.
- Two-phase `initialize`/`startup` and dependency declarations are two more concepts a manager author must understand versus a single `startup(context)` method.

### Option 4 (rejected, v0.1 draft): `RuntimeContext` carries named attributes per service (`context.config`, `context.event_bus`, ...)

Pros

- Fewer moving parts than a separate `ServiceContainer` — one object, direct attribute access.

Cons

- `RuntimeContext` becomes a growing god-object, gaining one hardcoded attribute per service forever — the exact `HeimeiConfig` shape ADR-0008 removed, recreated one layer up.

### Option 5 (rejected, v0.2 draft): Manual registration order, `startup()`/`shutdown()`/`health()` only (no `initialize()`)

Pros

- Simplest possible lifecycle — one activation method, one teardown method.

Cons

- Pushes correct ordering onto whoever assembles the Runtime by hand, with no verification, growing more error-prone as real inter-manager dependencies appear.
- Collapsing wiring and activation into one `startup()` call reintroduces the exact ordering hazard two-phase `initialize`/`startup` is designed to remove (a manager activating before another it depends on has finished registering itself).

---

## Consequences

Positive

- Dependency-based ordering means adding a new manager with real dependencies is a declaration (`dependencies = ("configuration",)`), not a manual reordering of `main.py`.
- The two-phase lifecycle removes an entire category of "resolved a service before it registered itself" bugs by construction, rather than relying on registration-order discipline.
- `HealthStatus` being a shared, frozen interface from day one means a future `heimei core status` command needs no per-manager special-casing to render results.
- Runtime and ServiceContainer remain independently replaceable: changing how order is derived, or how services are resolved, never requires touching the other.
- Configuration's frozen API (ADR-0008) is validated again as sufficient for a consumer at a different architectural layer — nothing here needs more from Configuration than `get_configuration_service()`/`.get()`.
- The plugin system, event system, and scheduler (the other reserved `Core/` subdirectories) still have an obvious attachment point without being designed today.

Negative

- More upfront machinery (topological sort, two-phase lifecycle) than the system's current single manager needs — justified by the explicit approval to build it ahead of the second and third manager, not by current necessity.
- Cycle and missing-dependency detection must produce genuinely clear errors, or dependency-based ordering becomes harder to debug than the manual ordering it replaced.

Trade-offs

- Deliberately not solving plugin discovery, scheduling, or cross-manager events here, even though their directories already exist under `Core/` — building them before a second and third manager exist to validate the design would repeat the mistake corrected in Configuration (ADR-0008, v1.1/v1.2).
- `ServiceContainer.get()`/`has()` are keyed by type, assuming one instance per type is ever registered — reasonable for singleton-style services, revisit only if a real need for multiple instances of one type appears.
- `HealthStatus`'s three states and free-text detail are intentionally coarse; a manager needing richer diagnostics exposes that through its own API, not by extending the shared interface.

---

## Future Work

- Plugin discovery (entry-points or directory scan) that produces `Manager` instances for the Runtime to register — maps to `Core/plugins/`; likely becomes the real content of ADR-0003.
- An in-process event bus for cross-manager notifications, registered into the `ServiceContainer` like any other service — maps to `Core/events/`; likely becomes the real content of ADR-0009.
- A scheduler for periodic manager tasks — maps to `Core/scheduler/`.
- Persisted registry state across restarts (`Core/registry/`), if ever needed — not required for an in-process v1.
- `heimei core status` (or similar) CLI, surfacing each manager's name, resolved order, lifecycle state, and `health()` result, once there is more than one manager worth listing.
- The actual Logging / Memory / Model Router / Agent System / Security managers that would register with this Runtime as they're built (Logging Manager is next; see ADR-0012).
- None of the above should be started speculatively — per Stability, above, only build a given item once a real manager's implementation demonstrates the need.

---

## References

Related ADRs: ADR-0008 (Configuration Manager — the first, frozen manager; the model for how a manager's API should stay stable), ADR-0002 (folder-layout, unfilled — defines the root `Core/` subdirectories this Runtime maps onto), ADR-0003 (plugin-system, unfilled), ADR-0009 (event-system, unfilled) — both expected to gain real content once their scope is split out of this Runtime, ADR-0012 (Logging Manager — the next manager to build on top of this Runtime).

Documentation: `Knowledge/Documentation/Glossary.md` ("Core" definition), `Knowledge/Documentation/Standards.md` (Python conventions), `Projects/Heimei/src/heimei/core/` (implementation), `Projects/Heimei/tests/test_core_*.py` and `test_cli_main.py` (tests).
