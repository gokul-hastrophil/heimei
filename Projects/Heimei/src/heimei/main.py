import typer

from heimei.cli.version import app as version_app
from heimei.cli.status import app as status_app
from heimei.cli.doctor import app as doctor_app
from heimei.cli.info import app as info_app

app = typer.Typer(
    help="Heimei Personal AI Operating Layer",
    no_args_is_help=True,
)

app.add_typer(version_app, name="version")
app.add_typer(status_app, name="status")
app.add_typer(doctor_app, name="doctor")
app.add_typer(info_app, name="info")

if __name__ == "__main__":
    app()
