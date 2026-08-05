import pytest
from typer.testing import CliRunner

from heimei.cli.config import app
from heimei.config import reset_configuration_service

runner = CliRunner()


@pytest.fixture(autouse=True)
def reset_service_singleton():
    reset_configuration_service()
    yield
    reset_configuration_service()


@pytest.fixture(autouse=True)
def isolated_home(monkeypatch, tmp_path):
    monkeypatch.setenv("HEIMEI_HOME", str(tmp_path))


@pytest.fixture
def machine_yaml(tmp_path, valid_machine_manifest, write_machine_manifest):
    manifest_dir = tmp_path / "System" / "manifest"
    write_machine_manifest(manifest_dir, valid_machine_manifest)


def test_show_prints_config(machine_yaml):
    result = runner.invoke(app, ["show"])

    assert result.exit_code == 0
    assert "heimei" in result.stdout
    assert "kniti" in result.stdout


def test_show_missing_manifest_fails(tmp_path):
    result = runner.invoke(app, ["show"])

    assert result.exit_code == 1


def test_validate_succeeds(machine_yaml):
    result = runner.invoke(app, ["validate"])

    assert result.exit_code == 0
    assert "valid" in result.stdout.lower()


def test_validate_fails_on_missing_manifest():
    result = runner.invoke(app, ["validate"])

    assert result.exit_code == 1


def test_dump_yaml(machine_yaml):
    result = runner.invoke(app, ["dump"])

    assert result.exit_code == 0
    assert "hostname: heimei" in result.stdout


def test_dump_json(machine_yaml):
    result = runner.invoke(app, ["dump", "--format", "json"])

    assert result.exit_code == 0
    assert '"hostname": "heimei"' in result.stdout


def test_dump_unknown_format_fails(machine_yaml):
    result = runner.invoke(app, ["dump", "--format", "toml"])

    assert result.exit_code == 1
