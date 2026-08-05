# ADR-0015: Status Manager

Status: Accepted

Version: 1.0 (implemented and frozen 2026-08-06)

Date: 2026-08-06

Author: Gokul

Stability: Frozen. Implemented in `heimei.status` exactly as specified below, wired into `Application`, without modifying `heimei.config`, `heimei.core.container`, `heimei.core.runtime`, `heimei.core.context`, `heimei.core.manager`, `heimei.core.health`, `heimei.logging`, `heimei.inventory`, or `heimei.doctor`. The only touch to a frozen file is one new line in `heimei.core.application` — see Decision, "Wiring." Treat as stable infrastructure, per the same discipline applied to ADR-0008/0011/0012/0013/0014 — extend by adding a new field `StatusService.snapshot()` aggregates from an *existing* Runtime/Inventory/Doctor method, not by giving Status its own collectors or rules.

---

## Context

Five managers now exist on the frozen `heimei.core` Runtime/ServiceContainer contract: Configuration (ADR-0008), Core Runtime itself (ADR-0011), Logging (ADR-0012), Inventory (ADR-0013), and Doctor (ADR-0014). `heimei/status/` has existed as an empty stub since M1, and `heimei/cli/status.py` printed "Status subsystem is under development." Both `heimei.inventory.record.InventoryRecord`'s and `heimei.inventory.__init__`'s own docstrings already named "Status" as an anticipated future consumer of Inventory, alongside Doctor.

This ADR was specified in full before implementation — architecture, requirements, file layout, and testing scope were all given as the sprint's starting brief, not iteratively refined during a proposal round-trip the way ADR-0011 through ADR-0014 were. Two decisions were still made *during* implementation to keep every existing frozen file untouched; both are recorded under "Revision (v1.0)" below.

## Problem Statement

Heimei needs one place that answers "what is happening right now?" — distinct from, and never overlapping with, Doctor's "what is wrong?":

- **Never queries the operating system directly** — Status's only sources of fact are the Runtime it's given and the InventoryService/DoctorService it resolves from the container.
- **Never duplicates an Inventory collector** or **implements a diagnostic rule** — every field in a status view is data some other frozen subsystem already produced; Status counts and formats, it does not collect or judge.
- **Never mutates system state.**
- Presents Runtime state, registered managers, their lifecycle state and health, a machine/CPU/memory/storage/network/GPU/Docker summary, and Doctor's finding counts by severity — as one small, strongly-typed snapshot.

---

## Decision

Introduce real content for `heimei.status`: `models.py` holds the strongly-typed snapshot shape; `service.py` holds `StatusService`, the pure aggregator; `manager.py` holds the `Manager` lifecycle implementation. `heimei/cli/status.py` is rewritten to render a `StatusSnapshot`, replacing the placeholder.

### Architecture

```text
Runtime + InventoryService + DoctorService
              │
              ▼
        StatusService.snapshot() -> StatusSnapshot
              │
              ▼
         heimei status (CLI)
```

`StatusManager.initialize()` resolves `InventoryService` and `DoctorService` from the `ServiceContainer` — the same pattern `DoctorManager` uses for `InventoryService` — and constructs `StatusService` with all three (Runtime, Inventory, Doctor) exactly once. `StatusService.snapshot()` is the only public method: it reads `Runtime.managers` structurally, requests a refreshed Inventory read for every volatile category, runs every registered Doctor check, and tallies findings by severity. It never keeps its own cache — "what is happening right now" is only true if every `snapshot()` call reads fresh.

### Revision (v1.0) — two decisions made during implementation

1. **`StatusSnapshot`'s `RuntimeSummary`/`ManagerSummary` are Status's own models, not `heimei.core.runtime.ManagerRecord` embedded directly.** `ManagerRecord` is a plain dataclass; embedding it as a pydantic field type would work at runtime, but only if `heimei.core.runtime` happened to already be fully loaded by the time `heimei.status.models` needed it — a fragile, import-order-dependent guarantee (the exact class of bug ADR-0014 already hit once with Doctor). Copying the four fields (`name`, `order`, `state.value`, `health`) across in `StatusService.snapshot()` by structural attribute access — the same "read data, don't import the producer's concrete type" pattern Doctor's checks already use for Inventory's collector types — makes `heimei.status.models` need zero module-level `heimei.core` import at all, regardless of load order.
2. **`StatusManager` takes the `Runtime` instance as a constructor argument, not via `context.services.get(Runtime)`.** The `ServiceContainer` never holds a `Runtime` reference — adding one would mean `Application` registering `Runtime` into its own container, a small but real change to how Core Runtime is wired for every future manager, not just Status. Since `Application` already constructs `self.runtime` before registering any manager, handing that same instance directly into `StatusManager(self.runtime)` needs zero new capability from `ServiceContainer`/`Runtime` — it's the same kind of object-wiring `Application` already does, just with one more constructor argument.

### Wiring

`heimei.core.application.Application.__init__` gains one line: `self.runtime.register(StatusManager(self.runtime))`, after the existing three manager registrations. `StatusManager.dependencies = ("logging", "inventory", "doctor")`, so Runtime orders it last. This is the only change to a file inside the frozen `heimei.core` boundary; `container.py`, `runtime.py`, `context.py`, `manager.py`, `health.py`, `errors.py` are untouched.

### Circular-import safety

Like `heimei.doctor.manager` (ADR-0014), `heimei.status.manager` defers every `heimei.core`/`heimei.inventory`/`heimei.doctor`/`heimei.logging` import it needs at runtime to inside its methods (`from __future__ import annotations` + `TYPE_CHECKING` for type hints, local imports for real use) — `heimei.core.__init__` eagerly imports `Application`, which now imports `StatusManager`, so a module-level import in `status/manager.py` would risk the same class of circular import Doctor already hit once. `heimei.status.service` and `heimei.status.models` are designed to need zero real `heimei.core` import at all (see Revision item 1 above), which is a stronger guarantee than deferral — there's no runtime-dependent import to defer in the first place.

---

## Alternatives Considered

### Option 1: Embed `ManagerRecord` directly in `StatusSnapshot`

Pros: one field, no translation step in `StatusService`.
Cons: makes `heimei.status.models`'s safety depend on `heimei.core.runtime` already being loaded — an implicit, easy-to-break invariant. Rejected; see Revision item 1.

### Option 2: Register `Runtime` into the `ServiceContainer`

Pros: `StatusManager` could resolve it the same way it resolves `InventoryService`/`DoctorService`, one consistent pattern.
Cons: changes what the `ServiceContainer` holds for every future manager, not just Status — a small but real precedent change to Core Runtime's wiring, not just a Status-local decision. Rejected; see Revision item 2.

---

## Consequences

**Positive**

- Status is a pure aggregator: adding a new field to `StatusSnapshot` never requires new OS access, only reading one more thing an existing frozen subsystem already exposes.
- Zero changes to `heimei.config`, `heimei.logging`, `heimei.inventory`, `heimei.doctor`, or any file inside `heimei.core` except `application.py`'s one new line.
- `heimei status` and `heimei doctor` cannot be confused for one another at the API level: `StatusService` has no severity-driven exit code, and `DoctorService` has no lifecycle/Runtime awareness.

**Negative**

- `RuntimeSummary`/`ManagerSummary` duplicate the *shape* (not the logic) of `heimei.core.runtime.ManagerRecord` — if `ManagerRecord` ever gains a field Status should surface, that field needs adding in two places by hand.

**Trade-offs**

- `StatusService.snapshot()` always requests refreshed Inventory reads for volatile categories, meaning `heimei status` is never cheaper than the sum of Inventory's own collection cost (subprocess calls for GPU/Docker included) — deliberate, since a status view serving stale data would defeat its stated purpose.

---

## Future Work

- A `--json` output mode for `heimei status`, if a script ever needs to consume it programmatically — not requested, not built.
- Surfacing Configuration drift (declared `MachineManifest` vs. discovered `MachineSnapshot`) was named as future work in both ADR-0008 and ADR-0013 and remains exactly that — out of scope here too; Status only aggregates, it does not reconcile.

---

## References

- ADR-0011 (Core Runtime) — `Manager` protocol, `ServiceContainer`, `Runtime.managers`
- ADR-0013 (Inventory Manager) — `InventoryService`, and the "consumed by Status, Doctor" note in its own docstring
- ADR-0014 (Doctor Manager) — `DoctorService`, `Finding`/`Severity`, and the circular-import fix this ADR's Wiring section reuses
- `Projects/Heimei/docs/ARCHITECTURE.md` — updated alongside this ADR with Status's place in the component diagram
