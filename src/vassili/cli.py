"""CLI principal de VASSILI."""

import json
from pathlib import Path
from typing import Optional
import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from vassili.core.models import MutationReport, MutationStatus
from vassili.core.mutation_runner import run_mutation_analysis

app = typer.Typer(
    name="vassili",
    help="Motor de Mutation Testing en C para evaluar la efectividad de los tests",
    add_completion=True
)
console = Console()


@app.command()
def mutate(
    source_file: Path = typer.Argument(..., help="Archivo C a mutar", exists=True),
    tests_dir: Path = typer.Option(Path("tests"), "--tests-dir", "-t", help="Directorio con casos de prueba .in/.out", exists=True),
    min_score: float = typer.Option(70.0, "--min-score", "-m", help="Score mínimo de mutación para aprobar (0-100%)"),
    timeout: float = typer.Option(2.0, "--timeout", help="Timeout máximo por test en segundos"),
    json_output: bool = typer.Option(False, "--json", help="Emitir salida en formato JSON estructurado")
):
    """Genera mutantes sintéticos del código C y evalúa qué porcentaje es detectado por los tests."""
    report = run_mutation_analysis(source_file, tests_dir, timeout=timeout, min_score=min_score)

    if json_output:
        print(json.dumps(report.model_dump(), indent=2, ensure_ascii=False))
        if not report.passed:
            raise typer.Exit(code=1)
        return

    table = Table(title=f"Reporte de Mutation Testing ({source_file.name})", show_header=True, header_style="bold magenta")
    table.add_column("ID", style="cyan", width=4)
    table.add_column("Tipo", style="yellow", width=6)
    table.add_column("Línea", style="dim", width=6)
    table.add_column("Mutación Aplicada", style="white")
    table.add_column("Estado", style="bold", width=12)
    table.add_column("Test que lo Asesinó", style="blue")

    for m in report.mutants:
        if m.status == MutationStatus.KILLED:
            status_str = "[green]KILLED ✓[/green]"
        elif m.status == MutationStatus.SURVIVED:
            status_str = "[red]SURVIVED ✗[/red]"
        else:
            status_str = "[yellow]COMP_ERR[/yellow]"

        table.add_row(
            str(m.id),
            m.mutation_type,
            str(m.line_number),
            f"{m.original_snippet} ➔ {m.mutated_snippet}",
            status_str,
            m.killing_test or "—"
        )

    console.print(table)

    score_color = "green" if report.passed else "red"
    console.print(Panel(
        f"[bold]Mutantes Totales:[/bold] {report.total_mutants}\n"
        f"[bold green]Mutantes Asesinados (Killed):[/bold green] {report.killed_count}\n"
        f"[bold red]Mutantes Sobrevivientes (Survived):[/bold red] {report.survived_count}\n"
        f"[bold {score_color}]Mutation Score Final: {report.mutation_score}%[/bold {score_color}] (Mínimo requerido: {min_score}%)",
        title="[bold cyan]VASSILI Mutation Score[/bold cyan]"
    ))

    if not report.passed:
        raise typer.Exit(code=1)


@app.command()
def version():
    """Muestra la versión de VASSILI."""
    from vassili import __version__
    console.print(f"[bold cyan]VASSILI[/bold cyan] versión [green]{__version__}[/green]")


if __name__ == "__main__":
    app()
