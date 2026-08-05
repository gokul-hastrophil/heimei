---
generated: false
maintainer: Gokul
last_reviewed: 2026-08-06
references:
  - CONTRIBUTING.md
  - docs/ARCHITECTURE.md
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

## Tests

```bash
uv run pytest
```

251 tests as of the 0.2.0 release, one `tests/test_<package>_<component>.py` file per source module — `testpaths = ["tests"]` in `pyproject.toml`. `uv run pytest --cov` for coverage (`pytest-cov` is already a dev dependency).

## Linting

```bash
uv run ruff check .
```

Configured in `ruff.toml` at the project root: `line-length = 100`, `target-version = "py313"`, rule sets `E`, `F`, `I`, `UP`, `B`, `SIM`.

## Type checking

```bash
uv run mypy .
```

As of 0.2.0, this reports exactly one pre-existing error: `tests/test_cli_main.py:10`, a missing annotation on a test double's class attribute (`FakeApplication.instances = []`). Everything else is clean. If `mypy` reports anything beyond that one line, treat it as a real regression, not noise.

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
- Add a CI workflow (`.github/workflows/` is currently empty) running the three commands above on every push/PR — see `docs/ROADMAP.md`.

## Open Questions

- None at this time.

## Related Documents

- `CONTRIBUTING.md` — process and standards this setup supports
- `docs/ARCHITECTURE.md` — project layout and how the subsystems fit together
- `docs/ROADMAP.md` — CI and pre-commit-config are both tracked there as M2 candidates
