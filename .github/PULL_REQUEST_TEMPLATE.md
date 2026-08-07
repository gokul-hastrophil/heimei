<!--
Every section below is required — see AI_WORKFLOW.md, "PR lifecycle."
A PR missing any section, or with a placeholder-only answer in a
section that isn't legitimately "None", is incomplete regardless of
CI status. Open this PR as a draft, labeled status:draft-pr — not
status:review, which is applied only after CI is confirmed green, as
a separate trusted operation. Do not mark it "ready for review"
yourself — that is Gokul's action, taken during owner review.

If this PR was opened by Scripts/ai/dispatch.sh, every field in
Provenance below was generated from a trusted approval record and
dispatch attestation, not typed by hand — do not edit them.
-->

## Linked issue

Closes #

## Provenance

<!-- Filled in automatically by Scripts/ai/dispatch.sh for an
automated PR. For a human-authored PR, leave these blank or mark N/A —
they only apply to the trusted-approval workflow in AI_WORKFLOW.md. -->

| Field | Value |
|---|---|
| Approval ID | |
| Approval comment | |
| Claim ref | |
| Run ID | |
| Repository ID | |
| Implementation agent | |
| Base SHA | |
| Tested commit SHA | |
| Remote branch SHA | |

<!-- Review is a separate, explicit, owner-invoked step —
Scripts/ai/review.sh PR --issue N --approval-id ID
  --implementation-agent A --reviewer B
Nothing here auto-selects a reviewer; there is no "Review agent"
provenance field because review never runs as part of dispatch. -->

## Architecture summary

<!-- What changed, and why, in plain language. Reference the ADR this
implements or extends, if any. -->

## Files changed

<!-- Created vs. modified, grouped by purpose. -->

**Created:**

**Modified:**

## Behavior changed

<!-- What is different for a user or another subsystem after this merges?
"None — purely additive" is a valid, expected answer. -->

## Tests added

<!-- New/changed test files, and what they cover. -->

## Verification commands and output

<!-- Paste the ACTUAL command and its ACTUAL output — a restated summary
("tests pass") is not evidence. See AI_WORKFLOW.md, "Evidence requirements." -->

```console
$ uv run pytest
$ uv run ruff check .
$ uv run mypy src/heimei
```

<!-- Replace the three command lines above with their ACTUAL captured
output once you've run them — the fence above is a format example,
not a substitute for a real transcript. -->

## Frozen-subsystem touches

<!-- Name every frozen subsystem (see PROJECT.md) this PR's diff touches,
even incidentally, and the separate approval (issue link) authorizing
each one. "None" is a valid, expected answer. -->

## Dependency changes

<!-- New/changed Python dependencies, GitHub Actions, or external
services. "None" is a valid, expected answer. -->

## Security / privacy implications

<!-- Credentials, secrets, PII, new attack surface. "None" is a valid,
expected answer — don't skip this section. -->

## Migration impact

<!-- Does anything need to run, be reconfigured, or be backfilled for
this change to take effect? "None" is a valid, expected answer. -->

## Deferred work

<!-- What this PR deliberately does not do, and where that's tracked
(a ROADMAP.md item, a follow-up issue). -->

## Known limitations

<!-- Anything a reviewer should know that isn't a blocking problem. -->

## Merge recommendation

<!-- Implementer's and/or reviewer's honest assessment: ready for owner
review, or needs revision first, and why. This is a recommendation
only — Gokul decides and merges by hand. -->
