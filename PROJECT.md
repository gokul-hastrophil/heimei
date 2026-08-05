---
generated: false
maintainer: Gokul
last_reviewed: 2026-08-06
references:
  - Projects/Heimei/docs/ROADMAP.md
  - ROADMAP.md
  - State/Reports/m1-completion-review.md
---

# Heimei — Current Project State

## Purpose

Where things actually stand right now: current milestone, active work, frozen subsystems, and the immediate next steps. This is the one document in the governance set that's expected to go stale quickly — update it whenever a milestone closes, a subsystem freezes, or active work changes, rather than letting `CLAUDE.md`/`CONSTITUTION.md`/`VISION.md` (which shouldn't change often) absorb that churn instead.

## Scope

The whole `~/Heimei` workspace. `Projects/Heimei/docs/ROADMAP.md` covers that one software project's own tactical backlog in more detail than this document repeats.

## Current milestone

**Milestone M1 — done.** Tagged `v0.2.0`. Five subsystems (Configuration, Core Runtime, Logging, Inventory, Doctor) implemented, tested (251 tests), documented, and frozen — see the table below. `Projects/Heimei`'s own `README.md`, `CHANGELOG.md`, `CONTRIBUTING.md`, `docs/DEVELOPMENT.md`, `docs/ARCHITECTURE.md`, and `docs/ROADMAP.md` were filled in as part of closing this milestone. Full review: `State/Reports/m1-completion-review.md`.

## Frozen subsystems

| Subsystem | ADR | Status |
|---|---|---|
| Configuration | [0008](System/docs/Architecture/0008-configuration.md) | Accepted, frozen |
| Core Runtime | [0011](System/docs/Architecture/0011-core-runtime.md) | Accepted, frozen |
| Logging | [0012](System/docs/Architecture/0012-logging-manager.md) | Accepted, frozen |
| Inventory | [0013](System/docs/Architecture/0013-inventory-manager.md) | Accepted, frozen |
| Doctor | [0014](System/docs/Architecture/0014-doctor-manager.md) | Accepted, frozen |

Frozen means: don't change their behavior without a new proposal and explicit approval first, per `CONSTITUTION.md`. `heimei.cli`, `heimei.main`, and `pyproject.toml`/version metadata are *not* frozen in this sense — they're wiring/release mechanics, not one of the five ADR-governed subsystems.

## Not yet started

Everything else under `Projects/Heimei/src/heimei/` (`agents`, `backup`, `bootstrap`, `memory`, `models`, `services`, `status`, `ui`, `update`, `utils`, `workflows`) is a reserved, empty package — no design work has happened, no ADR exists yet. `heimei status`/`heimei doctor`/`heimei info` are the only CLI commands with real behavior beyond `version`; `heimei status` is still a placeholder. ADRs `0001`–`0007`, `0009`, `0010` are unfilled templates — filenames only, no decision recorded.

## Active work

This governance document set (`VISION.md`, `CONSTITUTION.md`, `CLAUDE.md`, this file, `ROADMAP.md`, `MEMORY_RULES.md`) — establishing the long-term mission and operating rules at the workspace root, distinct from `Projects/Heimei`'s own project-level docs. Being written on `docs/heimei-constitution`, not yet merged.

## Immediate roadmap

- **Strategic** (Stage 1 → Stage 6, Digital Twin): `ROADMAP.md` (this directory).
- **Tactical** (`Projects/Heimei`'s own next milestone — version-drift-style fixes, CI, a `heimei inventory` command, etc.): `Projects/Heimei/docs/ROADMAP.md`.

## Next Actions

- Update the frozen-subsystem table the moment a sixth manager is accepted.
- Update "Current milestone" the moment M2 is scoped and started.

## Open Questions

- None at this time.

## Related Documents

- `ROADMAP.md` — the strategic six-stage path this milestone is step one of
- `Projects/Heimei/docs/ROADMAP.md` — the tactical backlog for the one real software project
- `State/Reports/m1-completion-review.md` — the full M1 audit this summary is drawn from
- `CONSTITUTION.md` — what "frozen" obligates
