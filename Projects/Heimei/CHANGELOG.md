# Changelog

All notable changes to this project are documented here. Format loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.2.0] — 2026-08-06 — Milestone M1

The first release with real subsystems. Five components, each taken through the same cycle — proposal ADR → refinement → approval → implementation → freeze — are implemented, tested, and merged.

### Added

- **Configuration Manager** ([ADR-0008](../../System/docs/Architecture/0008-configuration.md)): manifest loader, `ConfigurationService`, typed Pydantic models, validation, per-manifest caching, clear error hierarchy. `heimei config show/validate/dump`.
- **Core Runtime** ([ADR-0011](../../System/docs/Architecture/0011-core-runtime.md)): `Application`, `ServiceContainer`, `Runtime`, the `Manager` protocol, `RuntimeContext`, and a shared `HealthStatus` interface. Dependency-derived startup order; strict two-phase lifecycle (every manager's `initialize()` before any `startup()`).
- **Logging Manager** ([ADR-0012](../../System/docs/Architecture/0012-logging-manager.md)): the one structured-logging interface every manager uses; console and file sinks; `System/manifest/logging.yaml` as the first non-machine manifest.
- **Inventory Manager** ([ADR-0013](../../System/docs/Architecture/0013-inventory-manager.md)): read-only live machine state — `machine()`, `cpu()`, `python()`, `memory()`, `storage()`, `network()`, `gpu()`, `docker()` — with layered, never-raising discovery (e.g. GPU: `pynvml` → `nvidia-smi` → `lspci` → unavailable).
- **Doctor Manager** ([ADR-0014](../../System/docs/Architecture/0014-doctor-manager.md)): a rule engine evaluating Inventory snapshots into `Finding`s (CPU/Memory/Storage/Network/GPU/Docker checks). `heimei doctor`, exiting non-zero on any critical finding.
- `Application` wired into `heimei.main`'s CLI callback — every command now starts and stops the full manager lifecycle.
- 251 tests across 39 files; `ruff` and `mypy` both clean.
- `docs/ARCHITECTURE.md` and `docs/ROADMAP.md`, filled in from empty placeholders.

### Fixed

Six correctness bugs found by an automated PR review and confirmed against source before fixing:

- `Runtime.startup()` could be silently retried into a corrupted state after a manager failed mid-lifecycle; failure now shuts down whatever fully started and blocks a retry.
- `ConfigurationService.get()` returned the cached model instance directly; a caller mutating it corrupted the cache for every future caller. Now returns an independent copy.
- `LoggingManager` never removed loguru's default stderr sink when `console: false`, leaking log output in the wrong format.
- GPU and Docker collectors could crash if cleanup (`pynvml.nvmlShutdown()` / `client.close()`) raised inside a `finally` block, masking an otherwise-successful result.
- The CPU collector could crash on platforms where `psutil.cpu_freq()` raises `NotImplementedError`.
- Doctor's Storage check's WARNING message omitted the mount path and free-space percentage that its CRITICAL message included.
- The version drift between `pyproject.toml` (`0.1.0`) and `cli/version.py` (hardcoded `v0.2.0`): `cli/version.py` now reads `importlib.metadata.version("heimei")` instead of a literal string, so the two can't diverge again.

### Changed

- `cli/config.py`'s `dump` command now passes `markup=False` to Rich's console output, so literal `[...]` in configuration values isn't mangled.
- `cli/config.py`'s `validate` command's help text and output now correctly say "machine manifest" rather than implying it checks every manifest.
- Every previously-empty stub package (`agents`, `backup`, `bootstrap`, `memory`, `models`, `services`, `status`, `ui`, `update`, `utils`, `workflows`) and `cli/__init__.py` now carry a one-line docstring stating they're reserved and not yet implemented, matching the documentation style of the five implemented subsystems. Removed a stray, unused `main()` function left over from the initial scaffold in `heimei/__init__.py`.

## [0.1.0] — 2026-08-03

Initial scaffold: directory layout for every planned subsystem, a Typer CLI skeleton (`version`, `status`, `doctor`, `info` — only `info` genuinely functional at this point), `uv`/`ruff` project setup. No business logic.
