import typer

from heimei.cli.config import app as config_app
from heimei.cli.doctor import app as doctor_app
from heimei.cli.info import app as info_app
from heimei.cli.status import app as status_app
from heimei.cli.version import app as version_app
from heimei.core import Application

app = typer.Typer(
    help="Heimei Personal AI Operating Layer",
    no_args_is_help=True,
)


@app.callback()
def main(ctx: typer.Context) -> None:
    application = Application()
    application.start()
    ctx.obj = application
    ctx.call_on_close(application.stop)


app.add_typer(version_app, name="version")
app.add_typer(status_app, name="status")
app.add_typer(doctor_app, name="doctor")
app.add_typer(info_app, name="info")
app.add_typer(config_app, name="config")

if __name__ == "__main__":
    app()
