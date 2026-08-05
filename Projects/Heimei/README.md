# Heimei

**Personal AI Operating Layer.** A modular CLI that starts as infrastructure — configuration, structured logging, live machine inventory, and automated health checks — with more subsystems (agents, memory, workflows) planned on top.

> **Status: v0.2.0, pre-1.0.** Five subsystems are implemented, tested, and frozen (see below); everything else under `heimei.*` is a reserved, not-yet-implemented package. This is a single-machine personal project under active development, not a published/distributed tool.

## What's implemented

| Subsystem | What it does | ADR |
|---|---|---|
| **Configuration** | Single source of truth for manifest YAML — loads, validates, and caches it as typed Pydantic models. No other subsystem parses YAML directly. | [0008](../../System/docs/Architecture/0008-configuration.md) |
| **Core Runtime** | Orchestrates every manager's lifecycle (`initialize` → `startup` → `health`/`shutdown`), deriving startup order from declared dependencies. No business logic of its own. | [0011](../../System/docs/Architecture/0011-core-runtime.md) |
| **Logging** | The one logging interface every manager uses — structured, sink-routed (console + file today). Nothing outside it touches `loguru` directly. | [0012](../../System/docs/Architecture/0012-logging-manager.md) |
| **Inventory** | Read-only live machine state (CPU, memory, storage, network, GPU, Docker, Python) via layered discovery with graceful fallback. Single source of truth for "what does this machine actually have." | [0013](../../System/docs/Architecture/0013-inventory-manager.md) |
| **Doctor** | A rule engine that evaluates Inventory's snapshots into pass/warn/critical findings. Never touches the OS directly — only Inventory does. | [0014](../../System/docs/Architecture/0014-doctor-manager.md) |

Full architecture, diagrams, and how these compose at runtime: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). What's planned next: [`docs/ROADMAP.md`](docs/ROADMAP.md).

## Requirements

- Python ≥ 3.13 (developed against 3.14)
- [`uv`](https://docs.astral.sh/uv/) for dependency management

## Installation

```bash
git clone <this-repo>
cd Projects/Heimei
uv sync
```

This creates a local `.venv` and installs `heimei` in editable mode. Run commands with `uv run heimei ...`, or activate the venv (`source .venv/bin/activate`) and run `heimei ...` directly.

## Quickstart

```bash
uv run heimei --help          # list every command
uv run heimei version         # confirm the install
uv run heimei doctor          # run all health checks against this machine
```

Heimei reads its manifests from `$HEIMEI_HOME/System/manifest/` (default `HEIMEI_HOME` is `~/Heimei`). `heimei config`/`heimei doctor` need at least `System/manifest/machine.yaml` to exist there — see [`ConfigPaths`](src/heimei/config/settings.py) if you need to point somewhere else.

## CLI reference

Every top-level command is a Typer app registered in [`src/heimei/main.py`](src/heimei/main.py); running any of them constructs and starts the full `Application` (Configuration + Runtime + every manager) regardless of which command you called — see `docs/ARCHITECTURE.md`'s "CLI surface" section for exactly what each one resolves.

### `heimei version`

Prints the installed version, read from package metadata (so it can never drift from `pyproject.toml`).

```
$ heimei version
Heimei v0.2.0
```

### `heimei info`

Basic OS/platform information.

```
$ heimei info
Heimei
OS       : Linux
Release  : 7.0.0-28-generic
Machine  : x86_64
Python   : 3.14.4
```

### `heimei status`

Stub — not implemented yet. Currently just prints a placeholder; see `docs/ROADMAP.md` for the planned design (a composed summary over Logging/Inventory/Doctor).

```
$ heimei status
Status subsystem is under development.
```

### `heimei doctor`

Runs every registered health check (CPU, Memory, Storage, Network, GPU, Docker) against live Inventory data and prints one line per check — ✔ (ok), ⚠ (warning), or ✖ (critical), with the specific finding message for anything that isn't OK. **Exits with status 1 if any finding is critical** — useful in scripts.

```
$ heimei doctor
✔ CPU
✔ Memory
✔ Storage
✔ Network
✔ GPU
✔ Docker
```

### `heimei config show`

Loads and displays the current `machine.yaml` manifest as a table.

```
$ heimei config show
         Heimei Configuration
 (/home/kniti/Heimei/System/manifest)
┏━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━┓
┃ Key               ┃ Value           ┃
┡━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━┩
│ hostname          │ heimei          │
│ user              │ kniti           │
│ platform.os       │ ubuntu          │
│ platform.version  │ 26.04           │
│ hardware.cpu      │ Intel i5-11400H │
│ hardware.gpu      │ RTX3050         │
│ hardware.ram      │ 16GB            │
│ network.tailscale │ True            │
│ remote            │ macmini=True    │
└───────────────────┴─────────────────┘
```

### `heimei config validate`

Re-reads and validates the machine manifest from disk (bypassing any cache), exiting non-zero with a clear error on failure.

```
$ heimei config validate
machine manifest is valid (/home/kniti/Heimei/System/manifest)
```

### `heimei config dump [--format yaml|json]`

Dumps the fully validated configuration. Defaults to YAML; pass `--format json` for JSON.

```
$ heimei config dump
machine:
  hostname: heimei
  user: kniti
  platform:
    os: ubuntu
    version: '26.04'
  hardware:
    cpu: Intel i5-11400H
    gpu: RTX3050
    ram: 16GB
  network:
    tailscale: true
  remote:
    macmini: true
```

## Development

See [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md) for environment setup, running the test suite, linting, and type checking.

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md) — in particular, the ADR-driven process every subsystem above went through (propose → refine → approve → implement → freeze), and what "frozen" means for this project.

## Changelog

See [`CHANGELOG.md`](CHANGELOG.md).

## License

Not yet finalized — see [`LICENSE`](LICENSE).
