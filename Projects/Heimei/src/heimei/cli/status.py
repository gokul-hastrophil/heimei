import typer
from rich.console import Console

app = typer.Typer()
console = Console()


@app.callback(invoke_without_command=True)
def status():
    """System status."""
    console.print("[cyan]Status subsystem is under development.[/cyan]")
