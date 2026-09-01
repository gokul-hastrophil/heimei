# ADR-0017: Heimei–Paperclip Orchestration Boundary

Status: Proposed

Version: 1.0

Date: 2026-09-01

Author: Gokul

---

## Context

`VISION.md`'s "digital human model" commits Heimei, eventually, to a "Hands" capability — operating the keyboard, mouse, terminal, browser, cloud, IDE, and other applications on its human's behalf. `ROADMAP.md` places that under Stage 4 ("Skills") and Stage 5 ("Agent Ecosystem"), both explicitly `*(not started)*`. Reaching either stage means, at some future point, delegating real execution — driving tools, connectors, or external services — to something more broadly capable than Heimei's own process. This document uses **Paperclip** as the working name for that class of system: an external, execution-capable orchestration agent or framework Heimei could in principle direct to carry out multi-step actions across connectors, tools, and services. No specific product has been chosen, evaluated, or integrated. Nothing named "Paperclip" exists in this repository outside this ADR and its companion report.

`heimei.agents`, `heimei.workflows`, and the workspace's `Agents/` directory are reserved, empty stubs (`PROJECT.md`, "Not yet started"). No credential, connector, or execution authority for any such system is granted anywhere in this repository today, by this ADR or by anything preceding it.

`CONSTITUTION.md`'s Human Control section states the governing principle plainly: "Heimei must never become uncontrollable... Significant actions require explicit approval unless the owner has deliberately delegated that authority." `AI_WORKFLOW.md` already proves a concrete, mechanically-enforced version of that principle for Heimei's own development process — task-scoped, single-use, non-resumable approvals bound to an exact base state; fail-closed checks; no standing authority for any agent, including the one automated implementer it trusts today (Claude, with no Bash tool at all). Before any future Paperclip-class integration is even proposed in implementation detail, Heimei needs a recorded authority boundary — decided once, ahead of delivery pressure, per `CONSTITUTION.md`'s "ten-year sense check" — so a future integration proposal has a fixed reference point to be evaluated against, rather than re-litigating first principles under the pressure of "we already built most of it."

The name is chosen deliberately: it echoes the "paperclip maximizer" thought experiment in AI-safety literature — an optimizer pursuing a narrow goal without a bounded authority model, to the point of catastrophe. Embedding that reminder into the architecture record itself is intentional: it is exactly the failure mode this boundary exists to foreclose, not a joke at the future system's expense.

This ADR replaces the delivery of the same decision originally authorized under issue #12 (`risk:medium`, approved), whose own PR (#13) delivered this file and `PROJECT.md`'s note but not the companion report, and whose approval record is now fully consumed and non-resumable per `AI_WORKFLOW.md`'s "Atomic claim: no resume." This is a fresh implementation under a new, standalone approval (issue #17); it does not edit issue #12, does not reuse its approval, and does not resume PR #13's branch. The decision recorded below is the same decision issue #12 already approved — only the delivery mechanics differ.

---

## Problem Statement

How should authority, credentials, and control be divided between Heimei (the Digital Twin's intelligence, memory, and decision layer) and any future Paperclip-class external orchestration agent, such that:

- Heimei never grants an orchestrator standing, unsupervised authority to act on its behalf;
- every action an orchestrator ever performs is traceable to an explicit, task-scoped, human-approved authorization — never an inferred, ambient, or accumulated one;
- the boundary is recorded now, while no such integration exists, so a future proposal to actually build one is evaluated against a decision already made, not invented ad hoc under implementation pressure;
- this decision itself creates, stores, or exposes no credential, installs no connector, and grants no capability to anything — it is a boundary record, not an integration.

---

## Decision

Six rules, extending the same discipline `AI_WORKFLOW.md` already proves for Heimei's own development agents to any future Paperclip-class orchestrator. Full mechanical detail, a threat model, and the explicit no-credential statement this ADR does not restate live in the companion report, `State/Reports/heimei-paperclip-control-plane.md`.

1. **Heimei is always the authority root.** Any Paperclip-class orchestrator, if one is ever integrated, is a tool Heimei — and ultimately the human owner — directs. It is never a peer with independent standing authority over Heimei's data, memory, or decisions.
2. **No ambient authority.** An orchestrator receives only task-scoped grants — explicit, named actions/paths/connectors for one task — never a standing credential valid across tasks or sessions. This mirrors `AI_WORKFLOW.md`'s "Task-scoped authorization" and "Atomic claim: no resume" directly, rather than inventing a parallel model.
3. **Human approval precedes any capability grant.** Exactly as `CONSTITUTION.md`'s Human Control section requires, and as `AI_WORKFLOW.md` already enforces mechanically for Heimei's own development, no orchestrator is granted a new connector, credential, or capability without an explicit, recorded approval naming that specific capability.
4. **No credential lives unscoped in Heimei's own memory or knowledge layer.** Any credential a future orchestrator needs is held and injected by the orchestration boundary itself — a control plane analogous in spirit to `Scripts/ai/` — never embedded directly in Heimei's persistent memory (Stage 2 of `ROADMAP.md`, not yet built), where it could leak into reasoning output, logs, or a future export.
5. **Observation and action remain separate authority classes.** Heimei's existing read-only capabilities (Inventory, ADR-0013; Doctor, ADR-0014 — both frozen) stay strictly separate from any future write/act capability. Nothing in this ADR upgrades either frozen, read-only contract into write access, and no future orchestrator integration may claim otherwise.
6. **This ADR authorizes no implementation.** It records the boundary only. Building any part of a Paperclip integration — a connector, an MCP server, a credential, a line of orchestration code — requires its own future, narrowly-scoped ADR, taken through the full proposal → refinement → approval → implementation → freeze cycle `CONSTITUTION.md` requires of every subsystem, exactly like Configuration, Core Runtime, Logging, Inventory, Doctor, and Status before it.

---

## Architecture

```text
Human (Gokul)                    -- sole approval and delegation authority (CONSTITUTION.md)
    |
    v  explicit, task-scoped approval only (never standing, per rule 2/3 above)
Heimei                            -- Digital Twin: memory, reasoning, decisions (VISION.md)
    |
    v  orchestration boundary      -- NOT BUILT. Analogous in spirit to Scripts/ai/ + AI_WORKFLOW.md's
       (this ADR's authority          approval/claim/verification machinery, generalized beyond
        boundary; no code,            Heimei's own development agents to a future execution-capable
        no credential, no              orchestrator. Would hold/inject any credential; would enforce
        connector exists here)         task-scoped, single-use, revocable grants only.
    |
    v  task-scoped grant, one task, revocable, logged
Paperclip-class orchestrator      -- NOT SELECTED, NOT INTEGRATED, NOT BUILT.
    |
    v  bounded to the one granted task
Connectors / tools / external services   -- NONE EXIST TODAY

--------------------------------------------------------------------
Existing, unrelated, frozen read-only path (unaffected by this ADR):

InventoryService (ADR-0013, frozen) --read-only--> live machine facts
DoctorService     (ADR-0014, frozen) --read-only--> findings, never mutates
```

Everything below the "orchestration boundary" line is unbuilt today; this diagram states the authority direction such a system would have to respect, not a component inventory of something that exists.

---

## Alternatives Considered

### Option 1: Defer any boundary decision until an actual integration is proposed

Cons: leaves "how much authority does an executor get" undecided at exactly the moment implementation pressure is highest — the opposite of `CONSTITUTION.md`'s "ten-year sense check," and the same mistake `AI_WORKFLOW.md`'s own history (an earlier, weaker design later hardened after an adversarial review — see `State/Reports/ai-development-control-plane.md`) shows is costly to correct after the fact rather than before.

### Option 2: Grant Paperclip-class orchestrators standing, pre-approved authority for a defined action set

Cons: directly contradicts `CONSTITUTION.md`'s Human Control principle ("must never become uncontrollable") and the no-standing-authority model `AI_WORKFLOW.md` already proves works for Heimei's own development agents. This is precisely the paperclip-maximizer failure mode the name is chosen to warn against.

### Option 3 (accepted): Record the boundary now; authorize zero implementation; require every future capability grant to be its own explicit, narrowly-scoped approval

Pros: fixes the authority model before any delivery pressure exists to cut corners; reuses `AI_WORKFLOW.md`'s already-proven mechanisms (task-scoped grants, non-resumable approvals, fail-closed checks) instead of inventing a parallel model from scratch; keeps this decision genuinely reversible — `Status: Proposed`, no code, no dependency, no credential.

Cons: defers all concrete integration work, deliberately — that is Stage 4/5 territory (`ROADMAP.md`), not this ADR.

---

## Consequences

Positive

- Gives any future Paperclip-class integration proposal a fixed point of reference, decided ahead of delivery pressure.
- Extends the Human Control discipline `AI_WORKFLOW.md` already proves for Heimei's own development agents to a new domain before that domain exists, rather than inventing authority rules under implementation pressure later.
- Costs nothing today: no code, no dependency, no credential, no new attack surface.

Negative

- No orchestrator capability exists yet, so this boundary currently bounds nothing concrete — a deliberate ordering (rules before capability), not a defect in the design.

Trade-offs

- Writing this ADR ahead of Stage 4/5 trades "concreteness" (a boundary reads more abstractly before the system it bounds exists) for deciding the authority scope while no delivery pressure can distort that judgment — the same trade `CONSTITUTION.md`'s evaluation framework asks every architectural decision to make.

---

## Future Work

- The first concrete Paperclip-class integration proposal (Stage 4/5, `ROADMAP.md`) — its own ADR(s), scoped narrowly, evaluated against this boundary, not assumed to inherit authority from it.
- A credential-custody and orchestration-boundary design for whatever control plane such an integration eventually needs — the companion report sketches candidate shapes for discussion; none is authorized for implementation by this ADR.
- Whether Paperclip ultimately names one external product or a class of interchangeable orchestrators Heimei could direct — not decided here, deliberately.

---

## References

Related ADRs: ADR-0011 (Core Runtime — the frozen Manager/Service/Runtime contract any future orchestration boundary would need to compose with, not modify); ADR-0013 (Inventory Manager, frozen, read-only) and ADR-0014 (Doctor Manager, frozen, read-only) — the existing precedent this ADR keeps strictly separate from any future write/act authority (Decision, rule 5).

Documentation: `AI_WORKFLOW.md` (the proven task-scoped, non-resumable, fail-closed authorization model this boundary generalizes); `CONSTITUTION.md` (Human Control, and the evaluation framework this decision was weighed against); `VISION.md` (the "Hands" capability and digital-human model this boundary is drawn ahead of); `ROADMAP.md` (Stage 4 "Skills" / Stage 5 "Agent Ecosystem" — both not started); `State/Reports/heimei-paperclip-control-plane.md` (the companion design report — full mechanical detail, threat model, and the explicit no-credential statement, none of which is restated here).
