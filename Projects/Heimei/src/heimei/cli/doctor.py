import typer
from rich.console import Console

from heimei.doctor import Finding, Severity
from heimei.doctor.service import DoctorService

app = typer.Typer()
console = Console()

_ICON = {
    Severity.OK: "[green]✔[/green]",
    Severity.WARNING: "[yellow]⚠[/yellow]",
    Severity.CRITICAL: "[red]✖[/red]",
}


@app.callback(invoke_without_command=True)
def doctor(ctx: typer.Context) -> None:
    """Run Heimei health checks."""
    service = ctx.obj.services.get(DoctorService)
    findings = service.run()

    findings_by_check: dict[str, list[Finding]] = {}
    for finding in findings:
        findings_by_check.setdefault(finding.check, []).append(finding)

    for check_name, check_findings in findings_by_check.items():
        problems = [finding for finding in check_findings if finding.severity is not Severity.OK]
        if problems:
            for problem in problems:
                console.print(f"{_ICON[problem.severity]} {problem.message}")
        else:
            console.print(f"{_ICON[Severity.OK]} {check_name}")

    if any(finding.severity is Severity.CRITICAL for finding in findings):
        raise typer.Exit(code=1)
