<!--
Every section below is required — see AI_WORKFLOW.md, "PR lifecycle."
A PR missing any section is incomplete regardless of CI status.
Open this PR as a draft. Do not mark it "ready for review" yourself —
that is Gokul's action, taken during owner review.
-->

## Linked issue

Closes #

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

```
$ uv run pytest


$ uv run ruff check .


$ uv run mypy src/heimei

```

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

## Implementation agent

<!-- claude / codex / human -->

## Review agent

<!-- The other agent from Implementation agent above — see
AI_WORKFLOW.md, "one agent per implementation branch." Attach
Scripts/ai/review.sh output, or state it's pending. -->

## Merge recommendation

<!-- Implementer's and/or reviewer's honest assessment: ready for owner
review, or needs revision first, and why. This is a recommendation
only — Gokul decides and merges by hand. -->
