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


def generar_seccion_markdown(report: MutationReport) -> str:
    """Genera sección de análisis de efectividad de tests y mutation testing para Dredd."""
    lines = [
        "<!-- dredd-section: vassili v1.0.0 -->\n",
        "## Pruebas de Mutación y Calidad de Tests (Vassili)\n",
    ]
    lines.append(f"- **Archivo mutado:** `{Path(report.source_file).name}`")
    lines.append(f"- **Mutantes generados:** {report.total_mutants}")
    lines.append(f"- **Mutantes asesinados (Killed):** {report.killed_count}")
    lines.append(f"- **Mutantes sobrevivientes (Survived):** {report.survived_count}")
    lines.append(f"- **Mutation Score:** `{report.mutation_score}%`\n")
    if report.passed:
        lines.append("> [!TIP]\n> **Suite de Tests Efectiva:** La batería de pruebas detectó y eliminó los mutantes sintéticos satisfactoriamente.\n")
    else:
        lines.append("> [!WARNING]\n> **Tests Insuficientes:** Varios mutantes sobrevivieron a la suite de pruebas sin ser detectados.\n")
        lines.append("| ID | Tipo | Línea | Mutación | Estado | Test que lo detectó |")
        lines.append("| :---: | :---: | :---: | :--- | :---: | :--- |")
        for m in report.mutants:
            st = "✓ KILLED" if m.status == MutationStatus.KILLED else ("❌ SURVIVED" if m.status == MutationStatus.SURVIVED else "COMP_ERR")
            mut_str = f"{m.original_snippet} -> {m.mutated_snippet}".replace("|", "&#124;")
            test_str = (m.killing_test or "—").replace("|", "&#124;")
            lines.append(f"| {m.id} | `{m.mutation_type}` | {m.line_number} | `{mut_str}` | **{st}** | `{test_str}` |")
        lines.append("")
    return "\n".join(lines)


@app.command("mutate")
@app.command("check")
def mutate(
    source_file: Path = typer.Argument(..., help="Archivo C a mutar", exists=True),
    tests_dir: Path = typer.Option(Path("tests"), "--tests-dir", "-t", help="Directorio con casos de prueba .in/.out"),
    min_score: float = typer.Option(70.0, "--min-score", "-m", help="Score mínimo de mutación para aprobar (0-100%)"),
    timeout: float = typer.Option(2.0, "--timeout", help="Timeout máximo por test en segundos"),
    json_output: bool = typer.Option(False, "--json", help="Emitir salida en formato JSON estructurado"),
    output_md: Optional[Path] = typer.Option(None, "--md", "--output-md", help="Generar sección de reporte en formato Markdown para fusión en Dredd."),
):
    """Genera mutantes sintéticos del código C y evalúa qué porcentaje es detectado por los tests."""
    report = run_mutation_analysis(source_file, tests_dir, timeout=timeout, min_score=min_score)

    if output_md:
        md_text = generar_seccion_markdown(report)
        output_md.parent.mkdir(parents=True, exist_ok=True)
        output_md.write_text(md_text, encoding="utf-8")
        console.print(f"[bold green]✓ Sección Markdown generada en:[/bold green] {output_md}")
        raise typer.Exit(code=0 if report.passed else 1)

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


@app.command("report")
def report_cmd(
    source_file: Path = typer.Argument(..., help="Archivo C a mutar", exists=True),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Ruta de destino del archivo Markdown."),
    tests_dir: Path = typer.Option(Path("tests"), "--tests-dir", "-t", help="Directorio con casos de prueba."),
):
    """Genera directamente la sección de reporte Markdown de VASSILI para Dredd."""
    report = run_mutation_analysis(source_file, tests_dir)
    md_content = generar_seccion_markdown(report)
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(md_content, encoding="utf-8")
        console.print(f"[bold green]✓ Reporte Markdown generado en:[/bold green] {output}")
    else:
        print(md_content)


@app.command()
def version():
    """Muestra la versión de VASSILI."""
    from vassili import __version__
    console.print(f"[bold cyan]VASSILI[/bold cyan] versión [green]{__version__}[/green]")


@app.command("doctor")
def doctor_cmd(
    json_output: bool = typer.Option(False, "--json", help="Emitir diagnóstico en formato JSON estructurado."),
) -> None:
    """Verifica el estado del entorno de VASSILI (Python, GCC)."""
    import shutil
    import sys
    diagnostico = []

    py_ok = sys.version_info >= (3, 10)
    diagnostico.append({
        "componente": "Python Runtime",
        "estado": "OK" if py_ok else "ERROR",
        "requerido": True,
        "detalle": f"Python {sys.version.split()[0]}",
    })

    gcc_path = shutil.which("gcc")
    diagnostico.append({
        "componente": "Compilador GCC",
        "estado": "OK" if gcc_path else "ERROR",
        "requerido": True,
        "detalle": gcc_path or "No encontrado (requerido para compilar mutantes C)",
    })

    todo_ok = py_ok and bool(gcc_path)

    if json_output:
        payload = {
            "schema_version": "1.0.0",
            "herramienta": "vassili",
            "ok": todo_ok,
            "componentes": diagnostico,
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        raise typer.Exit(code=0 if todo_ok else 1)

    tabla = Table(title="🏥 Diagnóstico del Entorno VASSILI (doctor)", border_style="cyan")
    tabla.add_column("Componente", style="bold white")
    tabla.add_column("Estado", justify="center")
    tabla.add_column("Detalle")

    for c in diagnostico:
        color = "bold green" if c["estado"] == "OK" else "bold red"
        simbolo = "✓" if c["estado"] == "OK" else "✗"
        tabla.add_row(c["componente"], f"[{color}]{simbolo} {c['estado']}[/{color}]", c["detalle"])

    console.print(tabla)
    if not todo_ok:
        console.print("\n[bold red]Instalá gcc (`sudo apt install gcc` o equivalente).[/bold red]")
        raise typer.Exit(code=1)



if __name__ == "__main__":
    app()
