from typer.testing import CliRunner

import heimei.main as main_module
from heimei.main import app

runner = CliRunner()


class FakeApplication:
    instances = []

    def __init__(self):
        self.started = False
        self.stopped = False
        FakeApplication.instances.append(self)

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True


def test_command_invocation_starts_and_stops_the_application(monkeypatch):
    FakeApplication.instances = []
    monkeypatch.setattr(main_module, "Application", FakeApplication)

    result = runner.invoke(app, ["version"])

    assert result.exit_code == 0
    (instance,) = FakeApplication.instances
    assert instance.started is True
    assert instance.stopped is True


def test_application_still_stops_when_command_exits_with_error(monkeypatch):
    FakeApplication.instances = []
    monkeypatch.setattr(main_module, "Application", FakeApplication)

    result = runner.invoke(app, ["config", "dump", "--format", "toml"])

    assert result.exit_code == 1
    (instance,) = FakeApplication.instances
    assert instance.started is True
    assert instance.stopped is True


def test_help_does_not_construct_the_application(monkeypatch):
    FakeApplication.instances = []
    monkeypatch.setattr(main_module, "Application", FakeApplication)

    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert FakeApplication.instances == []


def test_other_commands_still_work_with_the_runtime_wired_in():
    assert runner.invoke(app, ["version"]).exit_code == 0
    assert runner.invoke(app, ["status"]).exit_code == 0
    assert runner.invoke(app, ["info"]).exit_code == 0
    assert runner.invoke(app, ["doctor"]).exit_code == 0
