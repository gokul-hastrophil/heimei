# AGENTS.md

Codex's entry point into this repository. Read these, in order, before doing anything — none of their content is repeated here:

1. [`VISION.md`](VISION.md) — why Heimei exists
2. [`CONSTITUTION.md`](CONSTITUTION.md) — how every decision is evaluated; what "frozen" obligates
3. [`PROJECT.md`](PROJECT.md) — current milestone, active work, the frozen-subsystem table
4. [`AI_WORKFLOW.md`](AI_WORKFLOW.md) — the full multi-agent policy this file only summarizes for Codex specifically
5. `Knowledge/Documentation/Standards.md` — the workspace's own highest-priority convention document; read before generating any documentation, code, or config
6. The ADR named in your issue, under `System/docs/Architecture/` — check its `Status:` field; a filename is not evidence a decision was made
7. `Projects/Heimei/docs/DEVELOPMENT.md` and `docs/ARCHITECTURE.md` — project-level development setup and current component layout

## Verification commands

Run from `Projects/Heimei/`:

```bash
uv sync --locked
uv run pytest
uv run ruff check .
uv run mypy src/heimei
```

All three checks must pass before a PR is marked anything but draft. Paste actual output in the PR — see `AI_WORKFLOW.md`, "Evidence requirements." `Scripts/ai/verify.sh --mode developer --repo-root <path> --full` runs all of these against an explicit, validated checkout and produces machine-readable JSON output with REAL captured transcripts (never a synthesized PASS/FAIL) — it has no default mode or repo-root, and never infers the repository from your current directory, on purpose. `--mode dispatch` (requiring a dispatcher-owned run manifest) is the only mode the trusted dispatcher itself accepts as proof; you would only ever see `--mode developer` output.

## Frozen-subsystem policy

Configuration, Core Runtime, Logging, Inventory, Doctor, and Status are frozen — see `PROJECT.md` for the authoritative, current list. Do not change their behavior without a separate, explicit approval distinct from the issue you're working — including a fix that looks small and obviously correct. If your task exposes a real flaw in a frozen subsystem, make no changes and explain the flaw in your final response; do not patch it silently.

## Codex automated implementation is disabled

`Scripts/ai/dispatch.sh --agent codex` fails immediately, unconditionally, with no override flag: "Automated Codex implementation is disabled until a proven sandbox and network isolation boundary is available." This check runs before any GitHub call. If you are Codex reading this because you were asked to implement an approved issue via `dispatch.sh`, that path does not exist in v1 — the only automated implementer is Claude. See `AI_WORKFLOW.md`, "Codex implementation is disabled," for why: no CLI sandbox flag inspected for this design was empirically confirmed to enforce a boundary strong enough to trust unsupervised.

## No direct main changes, no merge permission

You never push to `main`, and you never merge anything — that is Gokul's action alone, always. You never implement automatically at all in v1 (see above) — your only role is as reviewer, and only when explicitly invoked with your name in `--reviewer codex`, and even then never automatically: `Scripts/ai/review.sh` prepares a sanitized local bundle and the exact `codex exec` command for the owner to run themselves, interactively, with their own credentials — it never invokes you itself (see "Codex review isolation" in `AI_WORKFLOW.md`: even a verified network-isolated sandbox can't run a real Codex review, since you need network access to reach your own model).

## What you are never authorized to do

- Implement an issue automatically via `dispatch.sh` — not supported for Codex in v1, at any risk tier.
- Be automatically invoked as a reviewer — only a human running the printed manual command counts.
- Push directly to `main`, or push anywhere.
- Merge anything, ever.
- Change `VISION.md` or `CONSTITUTION.md`.
- Accept or change an ADR's `Status:` field.
- Add a paid service, a new API key, or expose a credential.
- Touch a path outside the trusted approval record's allowed-paths list, or one of the hard-denied paths in `.ai/policy.toml` (`VISION.md`, `CONSTITUTION.md`, `.ai/`, `Scripts/ai/`, `.github/workflows/`, any frozen-subsystem path, any dependency manifest, any migration path) — mechanically checked, not left to your own judgment.

Full authorization model: `AI_WORKFLOW.md`, "Task-scoped authorization." A `status:approved` label by itself authorizes nothing — the actual authorization is a trusted approval-record comment on the issue, which the dispatcher validates independently every time.

## Evidence requirements

Every claim of "this works" or "this passes" is backed by the actual command and its actual output — not a restated summary. See `AI_WORKFLOW.md`.

## Reviewer mode (manual only)

You are read-only, always, and never automatically invoked. When Gokul runs `Scripts/ai/review.sh PR --issue N --approval-id ID --implementation-agent claude --reviewer codex`, the script prepares a sanitized local bundle (the complete local diff, fetched and reviewed with `git` directly — never GitHub's possibly-truncated `patch` field — plus the JSON schema) and prints the exact `codex exec` command; it does not run you. If Gokul chooses to run that command by hand and feed your response back, your identity as reviewer comes from the arguments Gokul supplied on the command line, cross-checked by the script against the trusted approval record — never from the PR body, branch name, or a comment alone. Check architecture fit, acceptance criteria, tests, security, frozen-subsystem boundaries, migrations, and documentation; respond only in the required JSON shape. You never edit a file, never push, never merge.

## Implementer mode: not available in v1

There is no automated implementer path for you. If you are somehow reading an implementer-mode prompt anyway, stop and say so in your final response — that would mean this document and `dispatch.sh`'s behavior have diverged, which is itself a bug to report, not a task to proceed with.
