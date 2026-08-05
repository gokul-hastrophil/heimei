from importlib.metadata import version as _package_version

import typer
from rich.console import Console

app = typer.Typer()
console = Console()


@app.callback(invoke_without_command=True)
def version():
    """Show Heimei version."""
    console.print(f"[bold green]Heimei[/bold green] v{_package_version('heimei')}")
