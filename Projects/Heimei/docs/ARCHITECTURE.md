---
generated: false
maintainer: Gokul
last_reviewed: 2026-08-06
references:
  - System/docs/Architecture/0008-configuration.md
  - System/docs/Architecture/0011-core-runtime.md
  - System/docs/Architecture/0012-logging-manager.md
  - System/docs/Architecture/0013-inventory-manager.md
  - System/docs/Architecture/0014-doctor-manager.md
---

# Heimei CLI — Architecture

## Purpose

Current-state map of `Projects/Heimei` after Milestone M1: what the five implemented subsystems are, how they depend on each other, and how the process actually starts up. This is a snapshot of *what exists*, not a design discussion — architectural decisions and their rationale live in the ADRs linked above; this document only shows how those decisions compose together in the running system.

## Scope

`Projects/Heimei`'s Python package (`src/heimei`) as of the M1 milestone (Configuration, Core Runtime, Logging, Inventory, Doctor — all implemented, tested, and frozen). Does not cover the still-empty stub packages (`agents/`, `backup/`, `bootstrap/`, `memory/`, `models/`, `services/`, `status/`, `ui/`, `update/`, `utils/`, `workflows/`) beyond noting where they'd eventually plug in — see `docs/ROADMAP.md`.

## Component diagram

```mermaid
graph TD
    CLI["heimei.main:app (Typer CLI)"]
    APP["Application<br/>(heimei.core)"]
    SC["ServiceContainer<br/>register / get / has"]
    RT["Runtime<br/>dependency order, two-phase lifecycle"]

    CFG["ConfigurationService<br/>(heimei.config)<br/>no lifecycle — registered directly"]

    LM["LoggingManager"]
    LS["LoggingService"]
    IM["InventoryManager"]
    IS["InventoryService"]
    DM["DoctorManager"]
    DS["DoctorService"]

    COL["heimei.inventory.collectors<br/>cpu / memory / storage / network / gpu / docker / machine / python"]
    CHK["heimei.doctor.checks<br/>cpu / memory / storage / network / gpu / docker"]
    SINK["heimei.logging.sinks<br/>console / file"]

    CLI --> APP
    APP --> SC
    APP --> RT
    APP -- "registers directly, no Manager" --> CFG
    CFG --> SC

    RT -- "registers, orders by dependencies" --> LM
    RT --> IM
    RT --> DM

    LM -- "initialize() reads" --> CFG
    LM -- "registers" --> LS
    LM --> SINK
    LS --> SC

    IM -- "dependencies=('logging',)" --> LM
    IM -- "registers" --> IS
    IS --> COL
    IS --> SC

    DM -- "dependencies=('logging','inventory')" --> LM
    DM -- "dependencies=('logging','inventory')" --> IM
    DM -- "registers" --> DS
    DS -- "checks read snapshots via" --> IS
    DS --> CHK
    DS --> SC

    CLI -- "ctx.obj.services.get(...)" --> SC

    classDef frozen fill:#eef,stroke:#446,stroke-width:1px;
    class CFG,LM,LS,IM,IS,DM,DS frozen;
```

Every box marked as a frozen subsystem (blue fill) went through the propose → refine → approve → implement → freeze cycle and has an Accepted ADR. `Application`, `ServiceContainer`, and `Runtime` are Core Runtime (ADR-0011) — the orchestration layer every manager plugs into, itself frozen but drawn unshaded here since it's infrastructure rather than a "subsystem" with its own domain data.

## Startup sequence

```mermaid
sequenceDiagram
    participant CLI as main.py callback
    participant App as Application
    participant RT as Runtime
    participant Log as LoggingManager
    participant Inv as InventoryManager
    participant Doc as DoctorManager

    CLI->>App: Application()
    App->>App: ServiceContainer()
    App->>App: register ConfigurationService directly
    App->>RT: Runtime(services)
    App->>RT: register(LoggingManager, InventoryManager, DoctorManager)
    CLI->>App: start()
    App->>RT: startup()
    RT->>RT: resolve order from declared dependencies<br/>(logging, then inventory, then doctor)

    Note over RT: Phase 1 — initialize() on every manager, in order
    RT->>Log: initialize(context)
    Log->>Log: read ConfigurationService, attach console sink
    Log->>RT: register LoggingService
    RT->>Inv: initialize(context)
    Inv->>Inv: resolve LoggingService
    Inv->>RT: register InventoryService
    RT->>Doc: initialize(context)
    Doc->>Doc: resolve LoggingService + InventoryService,<br/>register all built-in checks
    Doc->>RT: register DoctorService

    Note over RT: Phase 2 — startup() on every manager, in order
    RT->>Log: startup()  (attaches file sink)
    RT->>Inv: startup()  (no-op)
    RT->>Doc: startup()  (no-op)

    Note over RT: any failure in either phase shuts down<br/>whatever fully started, reverse order,<br/>and blocks a retry (fixed post-CodeRabbit review)

    CLI->>CLI: ctx.obj = application
    Note over CLI: on exit — ctx.call_on_close(application.stop)
    CLI->>App: stop()
    App->>RT: shutdown()
    RT->>Doc: shutdown()
    RT->>Inv: shutdown()
    RT->>Log: shutdown()  (detaches both sinks)
```

Two details that are easy to miss reading the source in isolation:

- **`ConfigurationService` is not in the dependency graph at all.** It's registered into the `ServiceContainer` before `Runtime.startup()` even runs, so every manager's `initialize()` can resolve it unconditionally — `LoggingManager` does, despite declaring `dependencies=()`. Deliberate (Configuration is stateless and lazy per ADR-0008), but it means "declared dependencies" only govern *manager-provided* services, not Configuration.
- **The two-phase split is real, not cosmetic.** All three managers finish `initialize()` before any of them runs `startup()`. This matters because `initialize()` is wiring (resolve dependencies, register a service) while `startup()` is activation (open a file handle, start something running) — a manager can never observe another manager mid-startup.

## Subsystem responsibilities

| Package | Owns | Never does |
|---|---|---|
| `heimei.config` | Loading, validating, and caching manifest YAML into typed Pydantic models | Parse YAML outside `loader.py`; know about any specific manifest's shape |
| `heimei.core` | Manager lifecycle orchestration, service registration, dependency ordering | Business logic of any kind |
| `heimei.logging` | Structured logging, sink routing (console/file today) | Let anything outside `heimei.logging.sinks` touch `loguru` directly |
| `heimei.inventory` | Read-only live machine state, layered hardware/tooling discovery | Change system state, reconcile configuration, judge health |
| `heimei.doctor` | Evaluate Inventory snapshots into Findings via independent, composable checks | Query the OS directly, mutate anything |

## Where this diagram will need to change next

See `docs/ROADMAP.md` for the actual plan — noted here only so the two documents don't drift: a sixth manager, `Application` potentially moving into `heimei.bootstrap`, and a direct `heimei inventory` CLI command are the changes most likely to touch this diagram next.
