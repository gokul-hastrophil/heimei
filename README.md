---
generated: false
maintainer: Gokul
last_reviewed: 2026-08-06
references: []
---

# Heimei

Personal, lifelong AI Operating Layer. See [`VISION.md`](VISION.md) for what that actually means and why it exists — this file is a navigation index, not a restatement.

## Start here

| Document | Answers |
|---|---|
| [`VISION.md`](VISION.md) | Why does Heimei exist? What's the end state? |
| [`CONSTITUTION.md`](CONSTITUTION.md) | How should any decision about Heimei be evaluated? |
| [`CLAUDE.md`](CLAUDE.md) | Operating instructions for an AI session working here |
| [`PROJECT.md`](PROJECT.md) | What's actually built right now? What's frozen? What's active? |
| [`ROADMAP.md`](ROADMAP.md) | What's the staged path from here to the vision? |
| [`MEMORY_RULES.md`](MEMORY_RULES.md) | Where does a given piece of knowledge belong, and how does it evolve? |

## The one real project

[`Projects/Heimei`](Projects/Heimei/README.md) — the CLI that is Stage 1 of the roadmap above. Has its own `README.md`, `CHANGELOG.md`, `CONTRIBUTING.md`, and `docs/` (`ARCHITECTURE.md`, `DEVELOPMENT.md`, `ROADMAP.md` — tactical, distinct from the strategic one at this level).

## Workspace taxonomy

| Directory | What it holds |
|---|---|
| [`Knowledge/`](Knowledge/README.md) | Curated, human-authored documentation — standards, glossary, workflow |
| [`State/`](State/README.md) | Machine-generated snapshots — ephemeral, superseded over time |
| [`System/`](System/docs/Architecture/) | ADRs (the actual architectural decision record) and manifests |

Full definitions of these and every other top-level directory: [`Knowledge/Documentation/Glossary.md`](Knowledge/Documentation/Glossary.md).

## Next Actions

- Keep this index in sync with the governance document set above — it should never need more than a one-line description per document.

## Open Questions

- None at this time.

## Related Documents

- `Knowledge/Documentation/Standards.md` — read before generating any new documentation, code, or config anywhere in Heimei
