---
generated: false
maintainer: Gokul
last_reviewed: 2026-08-06
references:
  - CONTRIBUTING.md
  - docs/ARCHITECTURE.md
  - AI_WORKFLOW.md
---

# Development

## Purpose

How to get `Projects/Heimei` running locally and how to verify a change before committing it. For *what* the project is and *why* a decision was made, see `README.md` and the ADRs under `System/docs/Architecture/`, not this document.

## Scope

Local development environment, running the test suite, linting, and type checking for `Projects/Heimei` only.

## Prerequisites

- Python ≥ 3.13. Developed against 3.14 (`.python-version` pins `3.14`; the committed `.venv` runs `3.14.4`).
- [`uv`](https://docs.astral.sh/uv/) — this project's package manager. `uv.lock` is committed; don't hand-edit dependencies in `pyproject.toml` without running `uv sync`/`uv add`/`uv remove` to keep the lock file consistent.

## Setup

```bash
cd Projects/Heimei
uv sync
```

Installs both runtime and dev dependencies (`mypy`, `pytest`, `pytest-cov`, `ruff`, `pre-commit`, plus type stubs) into `.venv`, and installs `heimei` itself in editable mode.

## Running the CLI locally

```bash
uv run heimei --help
```

or activate the venv (`source .venv/bin/activate`) and run `heimei` directly. Heimei reads manifests from `$HEIMEI_HOME/System/manifest/` (default `HEIMEI_HOME` is `~/Heimei`) — most commands need at least `machine.yaml` there to do anything useful; see `README.md`'s CLI reference for what each command needs.

**Checkouts outside `~/Heimei` must set `HEIMEI_HOME` explicitly.** `heimei.config.settings.ConfigPaths.home` defaults to `Path.home()/"Heimei"`, which is only correct when the repository genuinely lives at `~/Heimei`. Any other checkout — a GitHub Actions runner (repo at `$GITHUB_WORKSPACE`, `$HOME` is `/home/runner`), an isolated AI-dispatch worktree, or a manually cloned copy elsewhere on disk — must export `HEIMEI_HOME` pointing at that checkout's own root, or commands will silently resolve `System/manifest/` under the wrong `~/Heimei` and fail (or worse, read the wrong machine's manifest) instead of using the checkout actually being tested:

```bash
export HEIMEI_HOME="$(git rev-parse --show-toplevel)"
```

This is exactly what `.github/workflows/ci.yml` does (`HEIMEI_HOME: ${{ github.workspace }}`) and what `Scripts/ai/verify.sh` does for an isolated dispatch worktree — see that workflow's comments for the full explanation of the failure this avoids.

## Tests

```bash
uv run pytest
```

287 tests as of the M1 completion review (`State/Reports/m1-completion-review.md`), one `tests/test_<package>_<component>.py` file per source module — `testpaths = ["tests"]` in `pyproject.toml`. `uv run pytest --cov` for coverage (`pytest-cov` is already a dev dependency).

## Linting

```bash
uv run ruff check .
```

Configured in `ruff.toml` at the project root: `line-length = 100`, `target-version = "py313"`, rule sets `E`, `F`, `I`, `UP`, `B`, `SIM`.

## Type checking

```bash
uv run mypy src/heimei
```

This is the exact command CI (`.github/workflows/ci.yml`) and `Scripts/ai/verify.sh` run, and it is currently clean — no errors. If `mypy` reports anything, treat it as a real regression, not noise.

## Continuous Integration

`.github/workflows/ci.yml` runs `uv sync --locked`, `uv run pytest -q`, `uv run ruff check .`, and `uv run mypy src/heimei` — the same four verification commands documented above — on every pull request and on every push to `main`, on GitHub's own infrastructure. This is the deterministic quality gate `AI_WORKFLOW.md` describes: a human never has to trust a self-reported "tests pass," because CI re-runs the identical checks against the actual pushed commit. The workflow sets `HEIMEI_HOME: ${{ github.workspace }}` for the same checkout-root reason described above.

## Known rough edge: `pre-commit`

A `pre-commit` git hook is installed (`.git/hooks/pre-commit`), but no `.pre-commit-config.yaml` exists at the workspace root, so a plain `git commit` currently fails with `No .pre-commit-config.yaml file was found`. Every commit so far has used pre-commit's own documented escape hatch:

```bash
PRE_COMMIT_ALLOW_NO_CONFIG=1 git commit -m "..."
```

This is not `--no-verify` — it's pre-commit's intended way to say "run, but there's deliberately no config yet," and it's the correct thing to reach for until a `.pre-commit-config.yaml` is actually written (not part of this project's current scope — see `docs/ROADMAP.md`).

## Directory layout

See `docs/ARCHITECTURE.md`'s "Project layout" section — not repeated here.

## Next Actions

- Add `.pre-commit-config.yaml` (or remove the stray hook) so `PRE_COMMIT_ALLOW_NO_CONFIG=1` stops being necessary.

## Open Questions

- None at this time.

## Related Documents

- `CONTRIBUTING.md` — process and standards this setup supports
- `docs/ARCHITECTURE.md` — project layout and how the subsystems fit together
- `docs/ROADMAP.md` — pre-commit-config is tracked there as an M2 candidate
- `AI_WORKFLOW.md` — the control-plane policy CI serves as a deterministic quality gate for
