---
generated: false
maintainer: Gokul
last_reviewed: 2026-09-01
references:
  - Projects/Heimei/docs/ROADMAP.md
  - ROADMAP.md
  - State/Reports/m1-completion-review.md
  - AI_WORKFLOW.md
  - State/Reports/ai-development-control-plane.md
---

# Heimei — Current Project State

## Purpose

Where things actually stand right now: current milestone, active work, frozen subsystems, and the immediate next steps. This is the one document in the governance set that's expected to go stale quickly — update it whenever a milestone closes, a subsystem freezes, or active work changes, rather than letting `CLAUDE.md`/`CONSTITUTION.md`/`VISION.md` (which shouldn't change often) absorb that churn instead.

## Scope

The whole `~/Heimei` workspace. `Projects/Heimei/docs/ROADMAP.md` covers that one software project's own tactical backlog in more detail than this document repeats.

## Current milestone

**Milestone M1 — done.** Tagged `v0.2.0`. Six subsystems (Configuration, Core Runtime, Logging, Inventory, Doctor, Status) implemented, tested (287 tests as of this review), documented, and frozen — see the table below. `Projects/Heimei`'s own `README.md`, `CHANGELOG.md`, `CONTRIBUTING.md`, `docs/DEVELOPMENT.md`, `docs/ARCHITECTURE.md`, and `docs/ROADMAP.md` were filled in as part of closing this milestone. Full review: `State/Reports/m1-completion-review.md`.

## Frozen subsystems

| Subsystem | ADR | Status |
|---|---|---|
| Configuration | [0008](System/docs/Architecture/0008-configuration.md) | Accepted, frozen |
| Core Runtime | [0011](System/docs/Architecture/0011-core-runtime.md) | Accepted, frozen |
| Logging | [0012](System/docs/Architecture/0012-logging-manager.md) | Accepted, frozen |
| Inventory | [0013](System/docs/Architecture/0013-inventory-manager.md) | Accepted, frozen |
| Doctor | [0014](System/docs/Architecture/0014-doctor-manager.md) | Accepted, frozen |
| Status | [0015](System/docs/Architecture/0015-status-manager.md) | Accepted, frozen |

Frozen means: don't change their behavior without a new proposal and explicit approval first, per `CONSTITUTION.md`. `heimei.cli`, `heimei.main`, and `pyproject.toml`/version metadata are *not* frozen in this sense — they're wiring/release mechanics, not one of the six ADR-governed subsystems.

## Not yet started

Everything else under `Projects/Heimei/src/heimei/` (`agents`, `backup`, `bootstrap`, `memory`, `models`, `services`, `ui`, `update`, `utils`, `workflows`) is a reserved, empty package — no design work has happened, no ADR exists yet. `heimei doctor`/`heimei status`/`heimei info` are the CLI commands with real behavior beyond `version`; `heimei config show/validate/dump` also has real behavior. ADRs `0001`–`0007`, `0009`, `0010` are unfilled templates — filenames only, no decision recorded.

## Active work

Hardening the AI development control plane (`AI_WORKFLOW.md`, `AGENTS.md`, `.ai/policy.toml`, `Scripts/ai/`) after an adversarial security review found several core claims were not mechanically enforced — see `State/Reports/ai-development-control-plane.md` for the revised design (trusted approval records, exact-commit verification, restricted agent authority) and what remains manual (no branch protection configured on `main` yet; no CI-driven `status:review` transition).

ADR-0017 (Heimei–Paperclip Orchestration Boundary) has been proposed — `Status: Proposed`, not yet accepted — recording the authority boundary between Heimei and any future external orchestration agent, ahead of any Stage 4/5 (`ROADMAP.md`) implementation. No code, credential, or connector exists yet. See `System/docs/Architecture/0017-heimei-paperclip-boundary.md` and its companion `State/Reports/heimei-paperclip-control-plane.md`.

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
- `AI_WORKFLOW.md` — the control-plane policy governing how further work on this project gets authorized and dispatched
- `State/Reports/ai-development-control-plane.md` — the control plane's own architecture and current gaps
- `CONSTITUTION.md` — what "frozen" obligates
