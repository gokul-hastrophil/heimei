---
generated: false
maintainer: Gokul
last_reviewed: 2026-08-06
references:
  - VISION.md
  - CLAUDE.md
  - PROJECT.md
  - Knowledge/Documentation/Standards.md
---

# Heimei — Constitution

## Purpose

The architectural philosophy and engineering principles Heimei is built against. `VISION.md` states *why* Heimei exists; this document states *how* every decision toward that vision should be evaluated. `Knowledge/Documentation/Standards.md` covers tactical conventions (directory naming, Markdown/YAML shape, `ruff`/`mypy` settings) — a different altitude from this document, and this document does not restate it.

## Scope

Applies to every architectural decision in Heimei — every subsystem, every ADR, every document, every line of code, every test. Applies regardless of who or what is making the change, human or AI.

## What this constitution assumes

See `VISION.md` for the full statement. In short: Heimei is not building a chatbot, an assistant, or an automation framework — it is building a lifelong Digital Twin, one decision at a time, and every decision made today either preserves or erodes the ability to get there.

## Engineering principles

**Always optimize for:** understanding, knowledge, simplicity, maintainability, evidence, long-term thinking, clear ownership, modularity, reusability.

**Never optimize for:** short-term hacks, premature abstraction, cleverness, duplicate knowledge.

These aren't platitudes — they're the reason Heimei's subsystems so far (Configuration, Core Runtime, Logging, Inventory, Doctor) were each built through a proposal → refinement → approval → implementation → freeze cycle rather than written directly: the cycle exists specifically to force "does this actually reduce future complexity" to be answered before code is written, not after.

## The evaluation framework

Before proposing or implementing anything, ask:

1. Does this move Heimei toward becoming a trustworthy Digital Twin?
2. Does this preserve architectural clarity?
3. Does this reduce future complexity?
4. Will this still make sense in ten years?

If the honest answer to any of these is "no" or "unclear," that's a reason to stop and reconsider before implementing — not a checklist to satisfy after the fact.

## Human control

Heimei must never become uncontrollable. Significant actions require explicit approval unless the owner has deliberately delegated that authority. Heimei (and anyone or anything acting on its behalf) may observe, learn, research, prepare, recommend, plan, and automate *delegated* tasks — but it must remain transparent. Every recommendation must explain why, based on what evidence, and what alternatives exist.

In practice, in this repository, this is what "frozen subsystem" means: once an ADR is `Accepted` and a subsystem is implemented and tested, its behavior does not change without a new proposal and explicit approval — including a change that looks like a small, obviously-correct bug fix. The smallness of a fix is not a reason to skip the approval step; it's a reason the approval step should be fast.

## Role

Whoever — or whatever — is doing the work on Heimei is acting as a **Lead Architect and Senior Platform Engineer**, not a generic coding assistant executing tickets. The primary responsibility is preserving architectural integrity while moving Heimei toward its vision — which means it's expected and correct to push back, flag a concern, or ask a clarifying question before implementing something that fails the evaluation framework above, rather than silently complying with an instruction that would.

See `CLAUDE.md` for how this translates into concrete session-level operating rules for an AI collaborator specifically.

## Final mission

Every subsystem. Every document. Every ADR. Every line of code. Every test. Every architectural decision. Must move Heimei one step closer to becoming a lifelong AI Operating Layer that faithfully extends its human's intelligence, preserves their knowledge, amplifies their capabilities, and helps them create lasting value for the world.

## Next Actions

- None at this time — revisit only if a principle above is found to conflict with how the project is actually being built, not to add new principles opportunistically.

## Open Questions

- None at this time.

## Related Documents

- `VISION.md` — the mission this constitution serves
- `CLAUDE.md` — how this constitution translates into session-level AI operating instructions
- `PROJECT.md` — current state, for judging whether a specific decision actually applies these principles today
- `Knowledge/Documentation/Standards.md` — tactical conventions, a different altitude from this document
