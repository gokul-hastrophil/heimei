import pytest
from pydantic import ValidationError

from heimei.config.models import MachineManifest


def test_valid_manifest_parses(valid_machine_manifest):
    manifest = MachineManifest.model_validate(valid_machine_manifest)

    assert manifest.hostname == "heimei"
    assert manifest.user == "kniti"
    assert manifest.platform.os == "ubuntu"
    assert manifest.hardware.ram == "16GB"
    assert manifest.network.tailscale is True
    assert manifest.remote == {"macmini": True}


def test_missing_required_field_raises(valid_machine_manifest):
    del valid_machine_manifest["hostname"]

    with pytest.raises(ValidationError) as exc_info:
        MachineManifest.model_validate(valid_machine_manifest)

    assert any(err["loc"] == ("hostname",) for err in exc_info.value.errors())


def test_wrong_type_raises(valid_machine_manifest):
    valid_machine_manifest["network"]["tailscale"] = "not-a-bool"

    with pytest.raises(ValidationError):
        MachineManifest.model_validate(valid_machine_manifest)


def test_unknown_field_raises(valid_machine_manifest):
    valid_machine_manifest["unexpected"] = "surprise"

    with pytest.raises(ValidationError):
        MachineManifest.model_validate(valid_machine_manifest)


def test_network_and_remote_are_optional(valid_machine_manifest):
    del valid_machine_manifest["network"]
    del valid_machine_manifest["remote"]

    manifest = MachineManifest.model_validate(valid_machine_manifest)

    assert manifest.network.tailscale is False
    assert manifest.remote == {}
