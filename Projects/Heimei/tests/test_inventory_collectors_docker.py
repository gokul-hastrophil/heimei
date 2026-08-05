import subprocess
import sys
import types

import pytest

from heimei.inventory.collectors import docker


class FakeDockerClient:
    def __init__(self, version, fail_version=False, fail_close=False):
        self._version = version
        self._fail_version = fail_version
        self._fail_close = fail_close
        self.closed = False

    def version(self):
        if self._fail_version:
            raise RuntimeError("cannot connect to the Docker daemon")
        return {"Version": self._version}

    def close(self):
        self.closed = True
        if self._fail_close:
            raise RuntimeError("transport already closed")


class FakeDockerModule(types.ModuleType):
    def __init__(self, version=None, fail_from_env=False, fail_version=False, fail_close=False):
        super().__init__("docker")
        self._version = version
        self._fail_from_env = fail_from_env
        self._fail_version = fail_version
        self._fail_close = fail_close
        self.client: FakeDockerClient | None = None

    def from_env(self):
        if self._fail_from_env:
            raise RuntimeError("cannot connect to the Docker daemon")
        self.client = FakeDockerClient(
            self._version, fail_version=self._fail_version, fail_close=self._fail_close
        )
        return self.client


@pytest.fixture
def no_docker_sdk(monkeypatch):
    monkeypatch.setitem(sys.modules, "docker", None)


def install_fake_docker(monkeypatch, **kwargs):
    fake = FakeDockerModule(**kwargs)
    monkeypatch.setitem(sys.modules, "docker", fake)
    return fake


def only_docker_cli_on_path(monkeypatch):
    monkeypatch.setattr(
        docker.shutil, "which", lambda name: "/usr/bin/docker" if name == "docker" else None
    )


def fake_cli_version(monkeypatch, version="27.1.0"):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout=f"{version}\n", stderr="")

    monkeypatch.setattr(docker.subprocess, "run", fake_run)
    return calls


def test_engine_api_available_wins_immediately(monkeypatch):
    fake = install_fake_docker(monkeypatch, version="27.0.0")
    monkeypatch.setattr(docker.shutil, "which", lambda name: None)

    snapshot = docker.collect()

    assert snapshot.available is True
    assert snapshot.source == "docker-engine-api"
    assert snapshot.version == "27.0.0"
    assert fake.client is not None
    assert fake.client.closed is True


def test_sdk_not_installed_falls_through_to_cli(monkeypatch, no_docker_sdk):
    only_docker_cli_on_path(monkeypatch)
    calls = fake_cli_version(monkeypatch)

    snapshot = docker.collect()

    assert snapshot.available is True
    assert snapshot.source == "docker-cli"
    assert snapshot.version == "27.1.0"
    assert calls == [["docker", "version", "--format", "{{.Server.Version}}"]]


def test_engine_api_close_failure_does_not_lose_the_version(monkeypatch):
    install_fake_docker(monkeypatch, version="27.0.0", fail_close=True)
    monkeypatch.setattr(docker.shutil, "which", lambda name: None)

    snapshot = docker.collect()

    assert snapshot.available is True
    assert snapshot.source == "docker-engine-api"
    assert snapshot.version == "27.0.0"


def test_engine_api_cannot_connect_falls_through_to_cli(monkeypatch):
    install_fake_docker(monkeypatch, fail_from_env=True)
    only_docker_cli_on_path(monkeypatch)
    fake_cli_version(monkeypatch)

    snapshot = docker.collect()

    assert snapshot.source == "docker-cli"


def test_engine_api_version_call_fails_falls_through_to_cli(monkeypatch):
    install_fake_docker(monkeypatch, fail_version=True)
    only_docker_cli_on_path(monkeypatch)
    fake_cli_version(monkeypatch)

    snapshot = docker.collect()

    assert snapshot.source == "docker-cli"


def test_cli_binary_missing_reports_unavailable(monkeypatch, no_docker_sdk):
    monkeypatch.setattr(docker.shutil, "which", lambda name: None)

    snapshot = docker.collect()

    assert snapshot.available is False
    assert snapshot.version is None
    assert snapshot.source == "none"


def test_daemon_not_running_reports_unavailable_not_an_exception(monkeypatch, no_docker_sdk):
    """The docker CLI binary can exist while the daemon is stopped —
    `docker version` fails in that case; this must not raise, only
    report available=False, per ADR-0013 ("never raise because a
    subsystem is absent").
    """
    only_docker_cli_on_path(monkeypatch)

    def fake_run(cmd, **kwargs):
        raise subprocess.CalledProcessError(1, cmd, stderr="Cannot connect to the Docker daemon")

    monkeypatch.setattr(docker.subprocess, "run", fake_run)

    snapshot = docker.collect()

    assert snapshot.available is False


def test_collect_never_raises_on_subprocess_timeout(monkeypatch, no_docker_sdk):
    only_docker_cli_on_path(monkeypatch)

    def fake_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, 5)

    monkeypatch.setattr(docker.subprocess, "run", fake_run)

    snapshot = docker.collect()

    assert snapshot.available is False
