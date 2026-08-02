import platform

import typer
from rich.console import Console

app = typer.Typer()
console = Console()


@app.callback(invoke_without_command=True)
def info():
    """System information."""

    console.print("[bold]Heimei[/bold]")
    console.print(f"OS       : {platform.system()}")
    console.print(f"Release  : {platform.release()}")
    console.print(f"Machine  : {platform.machine()}")
    console.print(f"Python   : {platform.python_version()}")
