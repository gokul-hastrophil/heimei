import typer
from rich.console import Console
from rich.table import Table

from heimei.status.models import StatusSnapshot
from heimei.status.service import StatusService

app = typer.Typer()
console = Console()


def _format_bytes(n: int) -> str:
    return f"{n / (1024**3):.1f} GB"


def _host_line(snapshot: StatusSnapshot) -> str:
    machine = snapshot.machine
    return f"{machine.hostname} ({machine.system} {machine.release}, {machine.architecture})"


def _cpu_line(snapshot: StatusSnapshot) -> str:
    cpu = snapshot.cpu
    parts = [f"{cpu.logical_cores} logical cores"]
    if cpu.physical_cores is not None:
        parts.append(f"{cpu.physical_cores} physical")
    if cpu.max_frequency_mhz is not None:
        parts.append(f"{cpu.max_frequency_mhz:.0f} MHz max")
    return ", ".join(parts)


def _memory_line(snapshot: StatusSnapshot) -> str:
    memory = snapshot.memory
    available = _format_bytes(memory.available_bytes)
    total = _format_bytes(memory.total_bytes)
    return f"{memory.percent:.1f}% used ({available} available of {total})"


def _storage_line(snapshot: StatusSnapshot) -> str:
    mounts = snapshot.storage.mounts
    if not mounts:
        return "no mounts detected"
    root = next((mount for mount in mounts if mount.path == "/"), mounts[0])
    return f"{root.path}: {root.percent:.1f}% used ({len(mounts)} mount(s) tracked)"


def _network_line(snapshot: StatusSnapshot) -> str:
    interfaces = snapshot.network.interfaces
    if not interfaces:
        return "no interfaces detected"
    with_address = sum(1 for interface in interfaces if interface.address_count > 0)
    return f"{with_address}/{len(interfaces)} interface(s) with an address"


def _gpu_line(snapshot: StatusSnapshot) -> str:
    gpu = snapshot.gpu
    if not gpu.available:
        return "not available"
    names = ", ".join(gpu.device_names) or "unknown device"
    return f"available via {gpu.source} — {names}"


def _docker_line(snapshot: StatusSnapshot) -> str:
    docker = snapshot.docker
    if not docker.available:
        return "not available"
    return f"available — v{docker.version} ({docker.source})"


@app.callback(invoke_without_command=True)
def status(ctx: typer.Context) -> None:
    """Show what's happening on this machine right now.

    Answers "what is happening right now?", never "what is wrong?" — for
    that, run `heimei doctor`. Always exits 0 on a successful read,
    regardless of Doctor's finding counts; Status reports, it doesn't
    judge.
    """
    service = ctx.obj.services.get(StatusService)
    snapshot = service.snapshot()

    runtime = snapshot.runtime
    runtime_state = "running" if runtime.all_managers_started else "starting"
    console.print(f"[bold]Runtime[/bold]: {runtime_state} ({runtime.manager_count} managers)")

    managers_table = Table(title="Managers")
    managers_table.add_column("Name")
    managers_table.add_column("State")
    managers_table.add_column("Health")
    for manager in runtime.managers:
        health = manager.health_state or "unknown"
        managers_table.add_row(manager.name, manager.lifecycle_state, health)
    console.print(managers_table)

    machine_table = Table(title="Machine")
    machine_table.add_column("Key")
    machine_table.add_column("Value")
    machine_table.add_row("Host", _host_line(snapshot))
    machine_table.add_row("CPU", _cpu_line(snapshot))
    machine_table.add_row("Memory", _memory_line(snapshot))
    machine_table.add_row("Storage", _storage_line(snapshot))
    machine_table.add_row("Network", _network_line(snapshot))
    machine_table.add_row("GPU", _gpu_line(snapshot))
    machine_table.add_row("Docker", _docker_line(snapshot))
    console.print(machine_table)

    findings = snapshot.findings
    color = "red" if findings.critical else "yellow" if findings.warning else "green"
    counts = f"{findings.ok} ok, {findings.warning} warning, {findings.critical} critical"
    console.print(f"[bold]Doctor findings[/bold]: [{color}]{counts}[/{color}]")
