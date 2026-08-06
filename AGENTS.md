# AGENTS.md

Codex's entry point into this repository. Read these, in order, before doing anything — none of their content is repeated here:

1. [`VISION.md`](VISION.md) — why Heimei exists
2. [`CONSTITUTION.md`](CONSTITUTION.md) — how every decision is evaluated; what "frozen" obligates
3. [`PROJECT.md`](PROJECT.md) — current milestone, active work, the frozen-subsystem table
4. [`AI_WORKFLOW.md`](AI_WORKFLOW.md) — the full multi-agent policy this file only summarizes for Codex specifically
5. The ADR named in your issue, under `System/docs/Architecture/` — check its `Status:` field; a filename is not evidence a decision was made
6. `Projects/Heimei/docs/DEVELOPMENT.md` and `docs/ARCHITECTURE.md` — project-level development setup and current component layout

## Verification commands

Run from `Projects/Heimei/`:

```bash
uv run pytest
uv run ruff check .
uv run mypy src/heimei
```

All three must pass before a PR is marked anything but draft. Paste actual output in the PR — see `AI_WORKFLOW.md`, "Evidence requirements." `Scripts/ai/verify.sh` runs all three and produces machine-readable output if you need it.

## Frozen-subsystem policy

Configuration, Core Runtime, Logging, Inventory, Doctor, and Status are frozen — see `PROJECT.md` for the authoritative, current list. Do not change their behavior without a separate, explicit approval distinct from the issue you're working — including a fix that looks small and obviously correct. If your task exposes a real flaw in a frozen subsystem, stop and flag it; do not patch it silently.

## What you are never authorized to do

- Push directly to `main`.
- Merge anything, ever — merge is Gokul's action alone.
- Change `VISION.md` or `CONSTITUTION.md`.
- Accept or change an ADR's `Status:` field.
- Add a paid service, a new API key, or expose a credential.
- Work outside the scope your assigned issue declares.

Full authorization model: `AI_WORKFLOW.md`, "Task-scoped authorization."

## Evidence requirements

Every claim of "this works" or "this passes" is backed by the actual command and its actual output in your PR description — not a restated summary. See `AI_WORKFLOW.md`.

## Reviewer mode

When you are the reviewer (the issue is labeled for the *other* agent), you are read-only by default: fetch the PR's metadata and diff, check architecture fit, acceptance criteria, tests, security, frozen-subsystem boundaries, migrations, and documentation, and produce blocking vs. non-blocking findings. You never push, never merge, and only post a review to GitHub when explicitly run with `--post` — default output is local. See `Scripts/ai/review.sh`.

## Implementer mode

When you are the named implementer (`agent:codex` on an approved issue), work only inside the isolated branch/worktree `Scripts/ai/dispatch.sh` creates, only within the issue's declared scope, run the verification commands above before pushing, and open (or update) a draft PR filled in per `.github/PULL_REQUEST_TEMPLATE.md`. Stop and set `status:blocked` rather than improvise if you hit anything on the "never authorized" list, an ambiguity that changes what "done" means, or two failed correction attempts — see `AI_WORKFLOW.md`, "Failure and escalation behavior."
