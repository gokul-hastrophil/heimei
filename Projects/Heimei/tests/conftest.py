from pathlib import Path

import pytest
import yaml

VALID_MACHINE_MANIFEST = {
    "hostname": "heimei",
    "user": "kniti",
    "platform": {"os": "ubuntu", "version": "26.04"},
    "hardware": {"cpu": "Intel i5-11400H", "gpu": "RTX3050", "ram": "16GB"},
    "network": {"tailscale": True},
    "remote": {"macmini": True},
}


@pytest.fixture
def manifest_dir(tmp_path: Path) -> Path:
    return tmp_path / "manifest"


@pytest.fixture
def valid_machine_manifest() -> dict:
    return {k: (v.copy() if isinstance(v, dict) else v) for k, v in VALID_MACHINE_MANIFEST.items()}


def _write_machine_manifest(manifest_dir: Path, data: dict | str) -> Path:
    manifest_dir.mkdir(parents=True, exist_ok=True)
    path = manifest_dir / "machine.yaml"
    if isinstance(data, str):
        path.write_text(data)
    else:
        path.write_text(yaml.safe_dump(data))
    return path


@pytest.fixture
def write_machine_manifest():
    return _write_machine_manifest


def _write_logging_manifest(manifest_dir: Path, data: dict | str) -> Path:
    manifest_dir.mkdir(parents=True, exist_ok=True)
    path = manifest_dir / "logging.yaml"
    if isinstance(data, str):
        path.write_text(data)
    else:
        path.write_text(yaml.safe_dump(data))
    return path


@pytest.fixture
def write_logging_manifest():
    return _write_logging_manifest
