# Contributing

This is currently a single-maintainer personal project, not yet open to outside contributors. This document exists so the process that's already been followed for every subsystem so far is written down once, rather than re-explained in every session or PR.

## The ADR-driven cycle

Every subsystem in `heimei.*` so far (Configuration, Core Runtime, Logging, Inventory, Doctor) went through the same cycle before a line of implementation code was written:

1. **Proposal** — an ADR under `System/docs/Architecture/` (start from `System/docs/Templates/ADR_TEMPLATE.md`), `Status: Proposed`, describing the problem, the decision, and alternatives considered.
2. **Refinement** — the proposal is reviewed and revised, often more than once, before implementation starts. Judgment calls and open questions get their own section in the ADR rather than being silently decided.
3. **Approval** — the ADR moves to `Status: Accepted`.
4. **Implementation** — built to match the accepted ADR, with comprehensive tests. Implementation should not require changes to any other already-frozen subsystem; if it does, stop and get that change approved explicitly rather than making it as a side effect.
5. **Freeze** — once implemented and tested, the subsystem is frozen. Its ADR gains a version-numbered "Revision" section for any change made after freezing, however small, with the reason for the change.

**What "frozen" means in practice:** don't modify a frozen subsystem's public behavior without a new proposal/approval step first — including things that look like small bug fixes. If an automated review tool (CodeRabbit or similar) or your own testing finds a real bug in a frozen subsystem, the fix itself may be small, but treat pointing it out and getting it approved as a distinct step from applying it. Pure documentation (a docstring, a comment, an ADR's own "Revision" log) is not "behavior" and doesn't need this — code paths, return values, and error conditions do.

Check an ADR's `Status:` field before trusting its filename — several ADRs (`0001`–`0007`, `0009`, `0010`) exist as filenames implying real decisions were made (vision, folder layout, plugin system, memory, model router, agent system, security, event system, development standards) but are still the unfilled template. A filename is not evidence of a decision.

## Code standards

- **Formatting/linting**: [`ruff`](https://docs.astral.sh/ruff/), configured in `ruff.toml` (`line-length = 100`, `target-version = "py313"`, rule sets `E`, `F`, `I`, `UP`, `B`, `SIM`). Run `uv run ruff check .` before committing.
- **Type checking**: `mypy`. Run `uv run mypy .` — the project aims for a clean run; see `docs/DEVELOPMENT.md` for the one currently-known exception.
- **Tests**: `pytest`, one `tests/test_<package>_<component>.py` file per source module. New behavior needs a new or updated test in the matching file; don't rely on an unrelated test incidentally covering it.
- **No comments explaining *what* code does** — names should do that. A comment is for a non-obvious *why*: a hidden constraint, a workaround, an invariant a future reader could easily break.
- **Manager/Service pattern**: a new subsystem that needs a lifecycle should follow the existing shape — a `<Name>Manager` implementing the `Manager` protocol (`heimei.core.manager`) registered with `Runtime`, and a `<Name>Service` it registers into the `ServiceContainer` for everyone else to resolve. See `docs/ARCHITECTURE.md` for how the five existing ones fit together.

## Commit messages

This repo follows [Conventional Commits](https://www.conventionalcommits.org/): `type(scope): summary`, e.g. `feat(doctor): implement Doctor Manager (ADR-0014)`, `fix: address CodeRabbit findings on PR #1`, `docs: fill in ARCHITECTURE.md and ROADMAP.md`. Common types used so far: `feat`, `fix`, `docs`, `chore`.

## Before opening a PR

- `uv run pytest`, `uv run ruff check .`, `uv run mypy .` all pass (or any exception is one already documented in `docs/DEVELOPMENT.md`, not a new one).
- If the change touches a frozen subsystem, the ADR's Revision section is updated in the same PR, with the reason.
- There is currently no CI workflow configured (`.github/workflows/` is empty) — the checks above are manual until that changes; see `docs/ROADMAP.md`.

## Getting set up

See [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md).
