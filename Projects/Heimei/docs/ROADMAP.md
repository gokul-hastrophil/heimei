---
generated: false
maintainer: Gokul
last_reviewed: 2026-08-06
references:
  - State/Reports/m1-completion-review.md
  - State/Reports/engineering-report.md
  - ../../../ROADMAP.md
---

# Heimei CLI — Roadmap

## Purpose

What's next for `Projects/Heimei` after Milestone M1. Each item below is a candidate for its own proposal → approval → implementation → freeze cycle (the same cycle Configuration, Core Runtime, Logging, Inventory, and Doctor each went through) — this document tracks *what* to build next, not the design itself. Design happens in a new ADR under `System/docs/Architecture/` when a candidate is picked up.

This is the **tactical** roadmap for one project. For the **strategic** six-stage path (Foundation → Digital Twin) this project is Stage 1 of, see the workspace root's [`ROADMAP.md`](../../../ROADMAP.md) — that document doesn't repeat anything below, and this one doesn't repeat anything there.

## Scope

`Projects/Heimei` only. Workspace-wide items (multi-machine onboarding, `State/` casing cleanup, the global npm/Claude Code install issue) live in `State/Reports/engineering-report.md`, not here.

## Milestone M1 — done

Configuration (ADR-0008), Core Runtime (ADR-0011), Logging (ADR-0012), Inventory (ADR-0013), Doctor (ADR-0014). All Accepted, frozen, merged to `main` (PR #1, commit `5013318`). 251 tests, `ruff`/`mypy` clean. Full review: `State/Reports/m1-completion-review.md`.

**Suggested version for this milestone: `0.2.0`.** Rationale in the review linked above — still pre-1.0 (most planned subsystems are empty stubs, no CI yet), but a real MINOR bump over the 0.1.0 scaffold. Applying it means fixing the `pyproject.toml` / `cli/version.py` drift (below) in the same change, not just editing one number.

## Milestone M2 — candidate: small fixes

Small, low-risk items surfaced by the M1 review, roughly ordered by how self-contained they are:

1. **Fix the version drift.** `pyproject.toml` says `0.1.0`; `cli/version.py` hardcodes `v0.2.0`. Make `cli/version.py` read `importlib.metadata.version("heimei")` instead of a literal string, so there's one source of truth, then bump `pyproject.toml` to the version decided above.
2. **Add CI.** `.github/workflows/` currently has no workflow files. A minimal `lint + type-check + test` job on push/PR would have caught the version drift and would catch regressions going forward — the project has had a real test suite since M1, CI is the missing piece to make it self-enforcing.
3. **Route `cli/info.py` through `InventoryService`** instead of calling `platform.*` directly. It's the one place left that bypasses Inventory for data Inventory already collects (with proper fallback layering and provenance) — see Finding 1 in the M1 review.
4. **Add a `heimei inventory` CLI command.** Currently the only way to see Inventory's data is indirectly, through Doctor's findings. A direct dump command (raw or `--json`) is also the prerequisite for `State/Machine/`, `State/Discovery/`, `State/Inventory/` documents to eventually be regenerated automatically instead of by hand — see `State/Reports/engineering-report.md`, Finding 11.
5. **Fill in the empty top-level docs.** `README.md`, `CHANGELOG.md`, `CONTRIBUTING.md`, `LICENSE`, `docs/DEVELOPMENT.md` are all still 0 bytes. A short README (what Heimei is, how to run it, pointer to `docs/ARCHITECTURE.md` and the ADRs) is the highest-value one to write first.
6. **Fix the one remaining `mypy` gap.** `tests/test_cli_main.py:10` needs a type annotation on `FakeApplication.instances`. Trivial, just needs picking up.
7. **Delete dead scaffold code.** `src/heimei/__init__.py`'s leftover `main()` ("Hello from heimei!") is never called — the real entry point is `main.py:app`. Decide whether `__main__.py` should do something (`python -m heimei`) or stay retired.

**Status** is no longer a candidate here — it shipped as the sixth subsystem (ADR-0015, Accepted and frozen; see `PROJECT.md`'s frozen-subsystem table). `heimei status` is real.

## Milestone M3 — future, needs design work first

Everything below needs an actual ADR proposal (most of these are currently just placeholder filenames in `System/docs/Architecture/` — `0001` through `0007`, `0009`, `0010` — unfilled templates, not decisions) before implementation starts:

- **`heimei.agents`** — agent definitions/behavior. `Agents/` (workspace root) is the reserved data location; this package is the code.
- **`heimei.memory`** — the personal AI-memory taxonomy (`Memory/`'s `Archive/Decisions/Experiences/Goals/...`). Not populated yet at the data layer either.
- **`heimei.workflows`**, **`heimei.bootstrap`** — workflow execution and first-run/provisioning logic, respectively. `heimei.bootstrap` is also the candidate new home for `Application` if the `heimei.core` → concrete-subsystems import direction (noted in the M1 review) gets addressed.
- **`heimei.models`**, **`heimei.services`**, **`heimei.ui`**, **`heimei.update`**, **`heimei.backup`** — no design work has started on any of these; still empty stubs from the initial scaffold.
- **Plugin system, event system, model router, multi-agent system, security model** (ADRs `0003`, `0009`, `0005`, `0006`, `0007`) — larger architectural decisions that several of the packages above likely depend on; probably need to be designed before those packages are, not after.

## Smaller future work already noted inside frozen ADRs

Not new findings — carried forward from ADR "Future Work" sections so they don't get lost:

- A more general storage-mount filter in Doctor (fstype/read-only based, not path-based) once Inventory's `StorageMount` model gains that field (ADR-0014).
- A remote logging sink, added as a new module under `heimei.logging.sinks` with no change to `LoggingService`/`LoggingManager`'s public shape (ADR-0012).
- The `LoggingManager`/`InventoryManager`/`DoctorManager` lifecycle-boilerplate duplication (health()/shutdown() tracking) — worth a small shared helper in `heimei.core` before a sixth manager copies the pattern a fourth time (see M1 review, Finding 2).

## Next Actions

- Pick the first M2 item(s) to actually schedule.
- Open a new ADR when anything in M2/M3 is ready to move from "candidate" to "proposed."

## Open Questions

- Should the `heimei.core` → subsystem-managers import direction (Application importing every manager) be fixed by moving `Application` into `heimei.bootstrap`, or left as-is since the workaround (deferred imports) is already proven to work?

## Related Documents

- `State/Reports/m1-completion-review.md` — the review this roadmap was written from
- `Projects/Heimei/docs/ARCHITECTURE.md` — current-state diagram, for what's already built
- `State/Reports/engineering-report.md` — workspace-wide findings (multi-machine onboarding, `State/` casing, etc.) out of this project's scope
- `System/docs/Architecture/` — where every milestone above gets its own ADR before implementation
