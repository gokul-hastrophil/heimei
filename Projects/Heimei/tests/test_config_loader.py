import pytest

from heimei.config.errors import ManifestNotFoundError, ManifestParseError
from heimei.config.loader import load_manifest


def test_load_returns_raw_dict(manifest_dir, valid_machine_manifest, write_machine_manifest):
    path = write_machine_manifest(manifest_dir, valid_machine_manifest)

    raw = load_manifest(path)

    assert raw == valid_machine_manifest


def test_load_missing_file_raises_not_found(manifest_dir):
    missing = manifest_dir / "machine.yaml"

    with pytest.raises(ManifestNotFoundError) as exc_info:
        load_manifest(missing)

    assert str(missing) in str(exc_info.value)


def test_load_invalid_yaml_raises_parse_error(manifest_dir, write_machine_manifest):
    path = write_machine_manifest(manifest_dir, "hostname: [unclosed")

    with pytest.raises(ManifestParseError):
        load_manifest(path)


def test_load_non_mapping_yaml_raises_parse_error(manifest_dir, write_machine_manifest):
    path = write_machine_manifest(manifest_dir, "- just\n- a\n- list\n")

    with pytest.raises(ManifestParseError):
        load_manifest(path)


def test_load_empty_file_returns_empty_dict(manifest_dir, write_machine_manifest):
    path = write_machine_manifest(manifest_dir, "")

    assert load_manifest(path) == {}
