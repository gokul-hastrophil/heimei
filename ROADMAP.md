---
generated: false
maintainer: Gokul
last_reviewed: 2026-08-06
references:
  - VISION.md
  - PROJECT.md
  - Projects/Heimei/docs/ROADMAP.md
---

# Heimei — Roadmap (Foundation → Digital Twin)

## Purpose

The strategic path from today's CLI toward `VISION.md`'s Digital Twin, in six stages. This is the *strategic* roadmap — it does not list individual tasks, fixes, or PRs. `Projects/Heimei/docs/ROADMAP.md` is the *tactical* roadmap for the one real software project (version fixes, CI, individual CLI commands) and covers Stage 1 in far more operational detail than this document repeats.

## Scope

The full six-stage arc. Status markers below reflect what's actually built, checked against `PROJECT.md` — this document states the destination, not a promise about timing.

## Stage 1 — Engineering Platform *(in progress)*

The infrastructure everything later depends on.

- ✅ Configuration
- ✅ Runtime
- ✅ Logging
- ✅ Inventory
- ✅ Doctor
- ⬜ Status — CLI command exists as a placeholder only; no design work started

See `Projects/Heimei/docs/ROADMAP.md` for what's actually next inside this stage.

## Stage 2 — Persistent Memory *(not started)*

- Timeline
- Experiences
- Knowledge
- Relationships
- Engineering history

`Memory/` (workspace root) is reserved but empty; `heimei.memory` (code) is an empty stub. Needs its own ADR before any implementation — see `MEMORY_RULES.md` for how this stage's *documentation* (as opposed to its eventual runtime implementation) should evolve in the meantime.

## Stage 3 — Knowledge Engine *(not started)*

- Reasoning
- Connections
- Learning
- Long-term understanding

Depends on Stage 2 existing first — a knowledge engine needs something to reason over.

## Stage 4 — Skills *(not started)*

Browser, Terminal, Git, Cloud, Docker, Programming, Vision, Speech, Hearing, Automation, Design, Research, Writing, Communication.

Note: Inventory already *observes* some of this territory today (Docker presence, GPU, network) — that's read-only machine state, not a "skill" in this stage's sense (the ability to *act*: drive a browser, write code, operate a terminal on Heimei's own initiative). Don't conflate the two when this stage is eventually scoped.

## Stage 5 — Agent Ecosystem *(not started)*

Specialized workers: Planner, Researcher, Engineer, Reviewer, Architect, Business Agent, Marketing Agent, Operations Agent.

`heimei.agents` (code) and `Agents/` (workspace root) are both reserved and empty. Depends on Stage 4 (agents need skills to act with) and Stage 3 (agents need reasoning to plan with).

## Stage 6 — Digital Twin *(the destination)*

The system becomes a trusted lifelong engineering partner — see `VISION.md` in full.

## What "done" means at each stage

A stage isn't "done" when code exists — it's done when it's implemented, tested, documented, and frozen the same way Stage 1's five subsystems were: proposal ADR → refinement → approval → implementation → freeze (see `CONSTITUTION.md`). Skipping that cycle to move faster through a later stage is exactly the kind of short-term hack the constitution says never to optimize for.

## Next Actions

- Keep this document's status markers in sync with `PROJECT.md`'s frozen-subsystem table — update both together, not one without the other.
- Stage 2 gets its own ADR proposal before any implementation starts.

## Open Questions

- None at this time.

## Related Documents

- `VISION.md` — the destination this roadmap is a path toward
- `PROJECT.md` — current milestone and active work, updated more often than this document
- `Projects/Heimei/docs/ROADMAP.md` — Stage 1's tactical detail
- `MEMORY_RULES.md` — how Stage 2's territory should be documented before it's implemented
