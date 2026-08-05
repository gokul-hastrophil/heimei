import typer
import yaml
from rich.console import Console
from rich.table import Table

from heimei.config import ConfigurationError, MachineManifest, get_configuration_service

app = typer.Typer(help="Inspect and validate Heimei configuration.", no_args_is_help=True)
console = Console()
error_console = Console(stderr=True)


def _fresh_machine() -> tuple[MachineManifest, str]:
    """Load the machine manifest fresh from disk, or exit with a clear error."""
    service = get_configuration_service()
    try:
        machine = service.get("machine", MachineManifest, force=True)
    except ConfigurationError as exc:
        error_console.print(f"[bold red]Configuration error:[/bold red] {exc}")
        raise typer.Exit(code=1) from exc
    return machine, str(service.manifest_dir)


@app.command()
def show() -> None:
    """Show the currently loaded configuration."""
    machine, manifest_dir = _fresh_machine()

    table = Table(title=f"Heimei Configuration ({manifest_dir})")
    table.add_column("Key")
    table.add_column("Value")
    table.add_row("hostname", machine.hostname)
    table.add_row("user", machine.user)
    table.add_row("platform.os", machine.platform.os)
    table.add_row("platform.version", machine.platform.version)
    table.add_row("hardware.cpu", machine.hardware.cpu)
    table.add_row("hardware.gpu", machine.hardware.gpu)
    table.add_row("hardware.ram", machine.hardware.ram)
    table.add_row("network.tailscale", str(machine.network.tailscale))
    table.add_row("remote", ", ".join(f"{k}={v}" for k, v in machine.remote.items()) or "-")
    console.print(table)


@app.command()
def validate() -> None:
    """Validate all configuration manifests."""
    _, manifest_dir = _fresh_machine()
    console.print(f"[bold green]Configuration is valid[/bold green] ({manifest_dir})")


@app.command()
def dump(
    fmt: str = typer.Option("yaml", "--format", "-f", help="Output format: yaml or json"),
) -> None:
    """Dump the fully resolved, validated configuration."""
    if fmt not in ("yaml", "json"):
        error_console.print(f"[bold red]Unknown format:[/bold red] {fmt!r} (expected yaml or json)")
        raise typer.Exit(code=1)

    machine, _ = _fresh_machine()
    data = {"machine": machine.model_dump(mode="json")}
    if fmt == "json":
        console.print_json(data=data)
    else:
        console.print(yaml.safe_dump(data, sort_keys=False), end="")
