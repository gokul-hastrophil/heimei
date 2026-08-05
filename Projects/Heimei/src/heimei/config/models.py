from pydantic import BaseModel, ConfigDict


class PlatformInfo(BaseModel):
    """OS platform details for a machine."""

    model_config = ConfigDict(extra="forbid")

    os: str
    version: str


class HardwareInfo(BaseModel):
    """Hardware details for a machine."""

    model_config = ConfigDict(extra="forbid")

    cpu: str
    gpu: str
    ram: str


class NetworkInfo(BaseModel):
    """Networking details for a machine."""

    model_config = ConfigDict(extra="forbid")

    tailscale: bool = False


class MachineManifest(BaseModel):
    """Typed schema for ``System/manifest/machine.yaml``.

    Describes the machine Heimei is running on. ``remote`` is a free-form
    map of reachable-machine name to reachability flag (e.g. ``macmini:
    true``) so new machines can be added without a model change, matching
    the multi-machine design documented in
    ``Knowledge/Documentation/Standards.md``.
    """

    model_config = ConfigDict(extra="forbid")

    hostname: str
    user: str
    platform: PlatformInfo
    hardware: HardwareInfo
    network: NetworkInfo = NetworkInfo()
    remote: dict[str, bool] = {}
