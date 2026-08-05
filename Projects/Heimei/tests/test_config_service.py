import pytest
from pydantic import BaseModel

from heimei.config.errors import ManifestNotFoundError, ManifestValidationError
from heimei.config.models import MachineManifest
from heimei.config.service import (
    ConfigurationService,
    get_configuration_service,
    reset_configuration_service,
)


def test_get_returns_validated_manifest(
    manifest_dir, valid_machine_manifest, write_machine_manifest
):
    write_machine_manifest(manifest_dir, valid_machine_manifest)
    service = ConfigurationService(manifest_dir=manifest_dir)

    machine = service.get("machine", MachineManifest)

    assert machine.hostname == "heimei"


def test_missing_manifest_raises(manifest_dir):
    service = ConfigurationService(manifest_dir=manifest_dir)

    with pytest.raises(ManifestNotFoundError):
        service.get("machine", MachineManifest)


def test_invalid_manifest_raises_validation_error(
    manifest_dir, valid_machine_manifest, write_machine_manifest
):
    del valid_machine_manifest["hostname"]
    write_machine_manifest(manifest_dir, valid_machine_manifest)
    service = ConfigurationService(manifest_dir=manifest_dir)

    with pytest.raises(ManifestValidationError) as exc_info:
        service.get("machine", MachineManifest)

    assert "hostname" in str(exc_info.value)


def test_get_is_cached(manifest_dir, valid_machine_manifest, write_machine_manifest):
    write_machine_manifest(manifest_dir, valid_machine_manifest)
    service = ConfigurationService(manifest_dir=manifest_dir)

    first = service.get("machine", MachineManifest)
    (manifest_dir / "machine.yaml").unlink()
    second = service.get("machine", MachineManifest)

    assert first is second


def test_force_bypasses_cache(manifest_dir, valid_machine_manifest, write_machine_manifest):
    write_machine_manifest(manifest_dir, valid_machine_manifest)
    service = ConfigurationService(manifest_dir=manifest_dir)
    service.get("machine", MachineManifest)

    valid_machine_manifest["hostname"] = "renamed"
    write_machine_manifest(manifest_dir, valid_machine_manifest)
    reloaded = service.get("machine", MachineManifest, force=True)

    assert reloaded.hostname == "renamed"


def test_cache_is_keyed_by_manifest_name_not_shared_across_models(
    manifest_dir, valid_machine_manifest, write_machine_manifest
):
    """A cached entry for one model must never be handed back for another.

    Different manifests can share a cache dict keyed by name; if two
    subsystems ever called get() with the same name but different models,
    a naive cache would silently return the wrong type.
    """
    write_machine_manifest(manifest_dir, valid_machine_manifest)
    service = ConfigurationService(manifest_dir=manifest_dir)
    service.get("machine", MachineManifest)

    class UnrelatedModel(BaseModel):
        hostname: str

    result = service.get("machine", UnrelatedModel)

    assert isinstance(result, UnrelatedModel)


def test_get_configuration_service_returns_singleton():
    assert get_configuration_service() is get_configuration_service()


def test_reset_configuration_service_clears_singleton():
    first = get_configuration_service()
    reset_configuration_service()
    second = get_configuration_service()

    assert first is not second
