import typer
from rich.console import Console

app = typer.Typer()
console = Console()


@app.callback(invoke_without_command=True)
def doctor():
    """Run diagnostics."""
    console.print("[yellow]Doctor subsystem is under development.[/yellow]")
