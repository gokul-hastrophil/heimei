---
generated: false
maintainer: Gokul
last_reviewed: 2026-08-31
references:
  - CONSTITUTION.md
  - AI_WORKFLOW.md
  - PROJECT.md
  - State/Reports/heimei-paperclip-control-plane.md
---

# ADR-0017: Heimei–Paperclip Orchestration Boundary

Status: Proposed

Version: 1.0

Date: 2026-08-31

Author: Gokul

---

## Purpose

Records, as a single canonical and versioned decision, the Heimei-versus-Paperclip responsibility boundary approved in principle on issue #12's comment thread ("I approve Paperclip as Heimei's initial orchestration plane... Proceed with a dedicated ADR and threat model for the Heimei–Paperclip boundary."). This ADR is the stable document every future Paperclip-related implementation issue must cite for scope, authority limits, and required evidence, instead of reconstructing the boundary from conversation history — which `AI_WORKFLOW.md`'s core architectural rule ("GitHub is the control plane... never from 'what we discussed earlier'") forbids relying on.

## Scope

This ADR defines the responsibility split between Heimei and Paperclip, the actor authority model, the mandatory stop/escalation conditions, and the explicit non-goals of adopting Paperclip as an orchestration plane. It does not itself authorize implementation, deployment, connector installation, credentials, or any expanded agent authority — that approval, from the same comment thread, applies only to preparing this governed architecture proposal. Detailed threat model, schema, isolation validation plan, connector tiers, credential rules, resource limits, audit requirements, full migration plan, rollback plan, and pilot definitions live in the companion report, `State/Reports/heimei-paperclip-control-plane.md`, cross-referenced below rather than restated here.

---

## Context

Issue #11 evaluated Orka and a general event-driven control-plane topology, then pivoted after live inspection confirmed Paperclip `2026.824.1` is already installed and running locally (loopback-only UI and Postgres, Bubblewrap present, Claude Code and Codex CLI both authenticated). Gokul approved Paperclip as Heimei's initial orchestration plane on that thread, with the execution-harness interface — the component that actually runs an agent process inside an isolation boundary — kept replaceable for Orka or another backend later, so this decision is not re-litigated if the harness changes.

Today, the supervised-v1 control plane described in `AI_WORKFLOW.md` and implemented in `Scripts/ai/` is the only authorization and dispatch mechanism that exists. No ADR defines how a second, more capable orchestration layer (task graphs, scheduling, multi-connector execution) would relate to that existing authority model without either replacing it outright or silently inheriting its guarantees without earning them.

## Problem Statement

No ADR currently defines the Heimei/Paperclip boundary, no threat model exists for it, no actor capability/authority matrix has been formally recorded, no machine-readable task-contract/envelope schema exists, and no isolation validation plan has been written down. Without these, Paperclip cannot be given any write authority over this repository without repeating the "trust it because it's installed" mistake this issue's own thread already warned against for Orca/Orka. This ADR exists to close that gap on paper, before any of the capability it describes is built.

---

## Decision

Paperclip is adopted, in principle, as Heimei's initial **orchestration-plane** execution harness. Its responsibilities are strictly separated from Heimei's own **policy, authorization, memory, and governance plane**, which remains the sole source of truth for what any agent is authorized to do. This separation is not a convenience — it is the mechanism that prevents an orchestration tool's own primitives (task state, connector profiles, scheduling decisions) from ever becoming an implicit substitute for Heimei's actual authorization records.

Responsibility split:

- **Paperclip (orchestration plane):** task graph construction and scheduling, execution-workspace allocation, connector/tool policy *enforcement* at the harness level (never policy *origination*), and running the bounded correction loop for a task it has been handed.
- **Heimei (policy, authorization, memory, governance plane):** `VISION.md`, `CONSTITUTION.md`, accepted ADRs, `PROJECT.md`, and `.ai/policy.toml` remain the rule set; exact-base-SHA task authorization (see the report's "Task Contract / Envelope Schema") is issued only by Heimei's policy plane, never by Paperclip; frozen-subsystem protection and stop conditions (below) apply identically regardless of which execution harness runs a task; and no content Paperclip produces enters Heimei's durable memory except through a reviewed proposal path (see Non-Goals).
- **GitHub** remains durable development truth — issues, approval records, PRs, and their history — unchanged from `AI_WORKFLOW.md`.
- **Gokul** remains sole architecture-approval and merge authority, unchanged.
- **The execution harness** — the component that actually runs Claude, Codex, or another process adapter inside an isolation boundary — is specified as a *replaceable* component. Paperclip is one candidate implementation of this component today, not a hardwired dependency of the policy boundary itself.

This decision is recorded as `Status: Proposed`. Only Gokul changes an ADR's `Status` field, per `AGENTS.md`; nothing in this ADR or its companion report sets it to `Accepted`.

### Architecture

```text
GitHub (durable truth: issues, approval records, PRs, review history)
        │
        ▼
Heimei Policy / Authorization / Memory / Governance Plane
  VISION.md, CONSTITUTION.md, accepted ADRs, PROJECT.md, .ai/policy.toml
  - issues the task-contract/envelope (exact base SHA, allowed/denied paths,
    risk class, granted capabilities, limits, expiry — see report)
  - never delegates envelope-issuing authority to Paperclip
  - decides what, if anything, enters durable Heimei memory
        │  (signed-in-content envelope, single-use)
        ▼
Paperclip Orchestration Plane
  - task graph / scheduling
  - execution-workspace allocation
  - connector / tool policy enforcement (least-privilege tiers, see report)
  - bounded correction loop execution
        │  (bounded task + short-lived projected credentials, see report)
        ▼
Execution Harness (replaceable — Paperclip-managed sandbox today;
                   Orka or another backend could replace only this layer)
        │
        ▼
Agent process (Claude / Codex) — no durable credential, no standing authority
```

Actor capability and authority summary (full detail, including authority source and constraints per row, is in the report's "Actor Capability and Authority Matrix" section):

| Actor | Implement | Review | Merge | Self-Authorize |
|---|---|---|---|---|
| Gokul | Yes | Yes | Yes (sole) | Yes (is the authority) |
| Heimei policy plane | No | No | No | No — enforces authority, does not originate it for itself |
| Paperclip | No | No | No | No |
| Claude | Yes (scoped, no shell, per envelope) | Yes (read-only, when named) | No | No |
| Codex | No (automated implementation disabled) | Manual-only, owner-run | No | No |
| GitHub Actions | No | No (deterministic gate only) | No | No |
| Execution harness | No | No | No | No |

---

## Stop and Escalation Conditions

Regardless of which execution harness runs a task, an agent's task stops rather than proceeding, and escalates for human decision, when any of the following occurs:

1. Scope expands mid-task beyond the authorized envelope's allowed paths.
2. Any change would touch a frozen subsystem's behavior (`PROJECT.md`'s frozen-subsystem table / `.ai/policy.toml`'s `frozen_subsystems`).
3. Any change would conflict with an accepted ADR.
4. Any credential, secret, dependency, or migration implication arises that the envelope did not already authorize.
5. CI or tests do not go green within the bounded, authorized correction loop.
6. A reviewer disagrees with the implementer on a material architectural issue.
7. Any permanent, destructive, or external action would be required that exceeds delegated authority (merging, pushing to `main`, deleting persistent data, production deployment, or anything on `AI_WORKFLOW.md`'s "never covers" list).

These mirror `AI_WORKFLOW.md`'s existing "Failure and escalation behavior" and are stated here explicitly so they apply identically to any future Paperclip-mediated task, not only to the existing `dispatch.sh` path. Detection mechanics, routing, and operational response for each condition are specified in the report's relevant sections (Isolation Validation Plan, Audit and Evidence Requirements, Rollback Plan) rather than restated here.

## Non-Goals

Adopting Paperclip as an orchestration plane does **not**, by this ADR or by anything built under it:

- Authorize an automatic merge, ever.
- Authorize a direct push to `main` by Paperclip or any agent — the existing trusted-dispatcher-only push path is unchanged.
- Enable a globally-scoped "all connectors" tier for any connector, under any circumstance (see report, "Connector Permission Tiers").
- Expose any durable provider credential to an agent process — only short-lived, task-scoped projected credentials are ever permitted (see report, "Credential Ownership and Projection").
- Make any raw Paperclip transcript automatically canonical Heimei memory — it enters memory only through a reviewed proposal path, the same evidentiary bar `AI_WORKFLOW.md` already applies to PR evidence.
- Change `VISION.md` or `CONSTITUTION.md` — neither is touched by this line of work at any point.
- Authorize any implementation, pilot, dispatch run, or credential grant — this issue is architecture and threat-model documentation only; each later step (isolation-validation evidence, Pilot 1, Pilot 2, any connector rollout) requires its own separate, explicitly approved issue.

---

## Alternatives Considered

### Option 1: Build a bespoke Orka-based (or fully custom) event-driven control plane

Pros: no third-party orchestration dependency; full control over every primitive from day one.
Cons: issue #11 found no equivalent live-inspected, already-authenticated installation to build against — this would mean designing and validating an isolation boundary from scratch before any orchestration benefit is realized. Rejected for now in favor of building on a tool already confirmed installed and reachable, while keeping the harness interface replaceable so this option remains available later without re-deriving the policy boundary.

### Option 2: Keep the single-agent, one-shot `dispatch.sh` model indefinitely, with no orchestration plane

Pros: simplest possible design; already proven across several real dispatch runs.
Cons: does not scale to multi-task graphs, concurrent-but-non-overlapping work, or connector-mediated tasks Heimei will eventually need as its Digital Twin scope grows. Rejected as a permanent answer, though it remains the fallback path (see report, "Rollback Plan") for as long as Paperclip integration has no accepted isolation evidence.

### Option 3: Let Paperclip itself be the authorization and policy source of truth, not just the orchestration plane

Pros: fewer moving parts — one system for both scheduling and authorization.
Cons: repeats exactly the "trust it because it's installed" mistake this issue's own thread warned against for Orca/Orka; would mean Paperclip's own task/connector-profile primitives silently becoming authoritative over Heimei's `.ai/policy.toml`-derived rules. Rejected outright — see Decision, "Responsibility split," and report, "Task Contract / Envelope Schema," subsection "Mapping onto Paperclip primitives."

---

## Consequences

**Positive**

- The Heimei/Paperclip split moves from two issue-comment paragraphs to one canonical, versioned document every future Paperclip-integration issue can cite instead of re-deriving.
- The execution-harness interface stays swappable — replacing Paperclip with Orka or another backend later changes only that adapter layer, not this policy boundary.
- Every later Paperclip-integration issue inherits a pre-defined threat model, schema, and evidence bar instead of re-litigating them from scratch.

**Negative**

- Adds one more architecture document and one more report to keep in sync with `AI_WORKFLOW.md`/`.ai/policy.toml` as those evolve — a maintenance cost, accepted because the alternative (undocumented boundary) is what created the risk this ADR closes.
- Nothing in this ADR is proven yet — it commits to a direction and a required evidence bar, not to a working isolation guarantee, which could still turn out to be unachievable with Paperclip specifically.

**Trade-offs**

- This ADR intentionally defers all isolation proof to a later, separately gated issue (see report, "Isolation Validation Plan") rather than asserting an isolation guarantee now — slower, but consistent with `AI_WORKFLOW.md`'s existing standard that a boundary is trusted only once empirically demonstrated, never assumed from a CLI flag or a vendor's own claim.

---

## Future Work

Migration from the current supervised-v1 control plane proceeds in phases, summarized here (full phased plan, entry/exit criteria, and rollback mechanics are in the report's "Migration Plan" and "Rollback Plan" sections):

- **P0 (this issue):** architecture, threat model, schema, and validation-plan design only — no code, no deployment.
- **P1:** a dedicated isolation-validation-evidence issue executes the report's Isolation Validation Plan against a real Paperclip-managed sandbox and attaches real captured results.
- **P2:** Pilot 1, a read-only pilot (report, "Pilots").
- **P3:** Pilot 2, a narrowly scoped write pilot that still routes its actual commit/push through the existing trusted `Scripts/ai/dispatch.sh` (report, "Pilots").
- **P4:** broader connector-tier rollout and any persistent-memory integration, contingent on this ADR's acceptance and, separately, on ADR-0016 (Persistent Memory, issue #9) being accepted in its own right — not authorized here.

Throughout every phase, `AI_WORKFLOW.md` and `Scripts/ai/` keep working completely unmodified; this ADR changes no existing script behavior and authorizes no code change.

---

## References

- ADR-0016 (Persistent Memory, issue #9) — reserved for that issue's own architecture; not reused, renumbered, or altered here.
- `AI_WORKFLOW.md` — the supervised-v1 control plane this boundary extends without modifying.
- `CONSTITUTION.md` — the evaluation framework and Human Control principles this boundary must satisfy.
- `PROJECT.md` — current frozen-subsystem list and active-work state.
- `.ai/policy.toml` — the machine-readable policy this boundary must not weaken.
- `State/Reports/heimei-paperclip-control-plane.md` — full threat model, schema, isolation validation plan, connector tiers, credential rules, resource limits, audit requirements, migration plan, rollback plan, and pilot definitions.

## Next Actions

- File a dedicated isolation-validation-evidence issue implementing the report's Isolation Validation Plan, once this ADR is accepted.
- Do not file a Pilot 1 or Pilot 2 issue before that evidence issue's results are reviewed and accepted by Gokul.

## Open Questions

- Whether Paperclip's own task/connector-profile schema, as installed, can express every field in the report's task-contract/envelope schema without a custom adapter — deferred to the isolation-validation issue, not decided here.
- Whether ChatGPT should have any standing role reviewing Paperclip-mediated architecture changes specifically, beyond the general role already described in `AI_WORKFLOW.md` — not decided here.

## Related Documents

- `State/Reports/heimei-paperclip-control-plane.md` — companion design report with full operational detail for every deliverable summarized above.
- `AI_WORKFLOW.md` — the supervised-v1 workflow this boundary is layered alongside.
- `CONSTITUTION.md` — the evaluation framework this decision was checked against.
- `PROJECT.md` — current milestone and active-work state.
- `.ai/policy.toml` — machine-readable policy this boundary must remain consistent with.
