---
generated: false
maintainer: Gokul
last_reviewed: 2026-08-06
references:
  - Knowledge/Documentation/Glossary.md
  - Knowledge/Documentation/Standards.md
  - CLAUDE.md
---

# Heimei — Memory Rules

## Purpose

How knowledge in this repository should evolve over time, and how it relates to an AI collaborator's own memory. This document defines *rules for evolution and placement* — it does not redefine what `Knowledge/`, `State/`, or `Memory/` mean; `Knowledge/Documentation/Glossary.md` is the only place those terms get defined, and this document only links to it.

## Scope

Every place understanding about Heimei can live: the repository's own `Knowledge/`/`State/`/`Memory/` directories, ADRs, and an AI collaborator's own cross-session memory system, which lives outside this repository entirely.

## Two entirely different kinds of memory

It's easy to conflate these; they solve different problems and neither replaces the other.

**In-repository knowledge** (`Knowledge/`, `State/`, `Memory/`, ADRs) is meant to be readable by *anyone* — a human, or any future AI session, regardless of which model or tool it's running on. It travels with the repository. If Heimei were cloned onto a new machine with no memory of any prior conversation, everything needed to understand the project should already be here.

**An AI collaborator's own cross-session memory** (for a Claude Code session, this lives under `~/.claude/`, not under `~/Heimei/`) is that specific tool's private continuity mechanism — how *it* remembers how *this user* prefers to work, across arbitrary future repositories, not just this one. It is not portable, not meant for humans to read directly, and not a substitute for writing something down here if it matters to the project rather than to the working relationship.

**Rule:** if a fact is about Heimei — its architecture, its state, its history, its plans — it belongs in this repository, in the right place per the decision tree below, regardless of what any AI's own memory also happens to contain. If a fact is about how a specific person likes to collaborate in general (independent of Heimei), that's the AI's own memory system's job, not this repository's.

## Where does a new piece of information go?

1. **Is it a decision — a specific architectural choice with alternatives considered?** → An ADR under `System/docs/Architecture/`, `Status: Proposed` until actually accepted. A recommendation or observation is not a decision until it's written up this way — see `Knowledge/Documentation/Standards.md`.
2. **Is it a timestamped observation or snapshot — machine state, a discovery pass, a generated report?** → `State/`. Ephemeral by design; superseded documents move to `State/Archive/`. Never hand-edited into looking curated — regenerate it instead.
3. **Is it curated, stable, and expected to still be true in six months?** → `Knowledge/`. This is where a `State/` observation graduates to once it's been acted on or confirmed durable — e.g. a `State/Reports/` finding that gets fixed and is worth remembering *why* it happened, not just that it did, belongs in `Knowledge/` afterward, not left stranded in `State/` alone.
4. **Is it the personal AI-memory taxonomy itself** (`Memory/`'s `Archive/Decisions/Experiences/Goals/Identity/Preferences/Relationships/Sessions/Skills/Timeline/`, Stage 2 of `ROADMAP.md`)? → Not yet populated. This is Heimei's own eventual subsystem for remembering things *about its human*, built the same way every other subsystem was (ADR first). Don't pre-populate it ad hoc before that ADR exists — an ad hoc file here today would need to be reconciled with whatever schema Stage 2 actually adopts.
5. **Is it about the current milestone, active work, or what's frozen?** → `PROJECT.md` (workspace-wide) or the relevant project's own docs (e.g. `Projects/Heimei/docs/ROADMAP.md`), not `Knowledge/` — this kind of fact changes too fast to be "curated."
6. **Is it about how to collaborate with this specific person, independent of Heimei?** → An AI's own cross-session memory, not this repository, per the rule above.

## Never duplicate

The same rule as `Knowledge/Documentation/Standards.md`, restated here because memory-placement decisions are exactly where duplication creeps in: if a fact is stated somewhere, every other document links to it rather than restating it. This applies across the boundary in the previous section too — an AI's own memory system should note a Heimei-specific fact came from this repository, not silently re-derive or restate it as if it were the AI's own private knowledge.

## Next Actions

- Revisit this document once `Memory/`'s Stage 2 ADR actually exists — the placeholder rule in item 4 above should be replaced with a real one.

## Open Questions

- None at this time.

## Related Documents

- `Knowledge/Documentation/Glossary.md` — the definitions this document assumes
- `Knowledge/Documentation/Standards.md` — the no-duplication rule this document restates for the memory-placement case specifically
- `CLAUDE.md` — points here for how an AI collaborator's own memory relates to this repository
- `ROADMAP.md` — Stage 2, the eventual home for `Memory/`
