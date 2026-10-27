"""CLI principal de VASSILI."""

import json
from pathlib import Path
from typing import List, Optional
import typer
from yutani.cli import crear_app
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from vassili import __version__
from vassili.core.models import MutationReport, MutationStatus
from vassili.core.mutation_runner import resolver_suite, run_mutation_analysis
from vassili.core.plan_vasquez import NOMBRE_POR_DEFECTO, chequeos_sin_probar, escribir_plan

# Contrato de línea de comandos del ecosistema (-h/--help, --version/-v, errores de datos como
# mensajes) y textos de Typer en español, desde yutani (N-ECO-14).
app = crear_app(
    "vassili",
    __version__,
    "Motor de Mutation Testing en C para evaluar la efectividad de los tests",
    add_completion=True,
    no_args_is_help=False,
)
console = Console()


def _filas_por_operador(report: MutationReport) -> List[List[str]]:
    filas = []
    for familia, r in sorted(report.por_operador.items()):
        score = "—" if r.score is None else f"{r.score}%"
        filas.append([familia, str(r.generados), str(r.asesinados), str(r.sobrevivientes), str(r.equivalentes), score])
    return filas


def _quien_lo_mato(m) -> str:
    if m.killing_test and m.asercion:
        return f"{m.killing_test} ({m.asercion})"
    return m.killing_test or m.sugerencia or "—"


def generar_seccion_markdown(report: MutationReport) -> str:
    """Genera sección de análisis de efectividad de tests y mutation testing para Dredd."""
    status = "ok" if report.passed else "fail"
    lines = [
        f"<!-- dredd-section: vassili, tool=vassili, version=1.0.0, status={status} -->\n",
        "## Pruebas de Mutación y Calidad de Tests (Vassili)\n",
    ]
    lines.append(f"- **Archivo mutado:** `{Path(report.source_file).name}`")
    lines.append(f"- **Mutantes generados:** {report.total_mutants}")
    lines.append(f"- **Mutantes asesinados (Killed):** {report.killed_count}")
    lines.append(f"- **Mutantes sobrevivientes (Survived):** {report.survived_count}")
    if report.equivalent_count:
        lines.append(f"- **Mutantes equivalentes (fuera del score):** {report.equivalent_count}")
    if report.perfil != "completo":
        lines.append(f"- **Perfil de operadores:** `{report.perfil}`")
    if report.suite:
        lines.append(f"- **Suite (p1_test):** `{Path(report.suite).name}`")
    if report.aislamiento:
        lines.append(f"- **Aislamiento de cada corrida:** {report.aislamiento}")
    if report.plan_vasquez:
        lines.append(f"- **Chequeos de error sin probar:** {len(chequeos_sin_probar(report))} "
                     f"(plan de fallos para vasquez en `{Path(report.plan_vasquez).name}`)")
    lines.append(f"- **Mutation Score:** `{report.mutation_score}%`\n")
    if report.por_operador:
        lines.append("| Operador | Generados | Asesinados | Sobrevivientes | Equivalentes | Score |")
        lines.append("| :---: | :---: | :---: | :---: | :---: | :---: |")
        lines.extend("| `" + f[0] + "` | " + " | ".join(f[1:]) + " |" for f in _filas_por_operador(report))
        lines.append("")
    if report.passed:
        lines.append("> [!TIP]\n> **Suite de Tests Efectiva:** La batería de pruebas detectó y eliminó los mutantes sintéticos satisfactoriamente.\n")
    else:
        lines.append("> [!WARNING]\n> **Tests Insuficientes:** Varios mutantes sobrevivieron a la suite de pruebas sin ser detectados.\n")
        lines.append("| ID | Tipo | Línea | Mutación | Estado | Test que lo detectó / qué caso falta |")
        lines.append("| :---: | :---: | :---: | :--- | :---: | :--- |")
        for m in report.mutants:
            st = {MutationStatus.KILLED: "✓ KILLED", MutationStatus.TIMEOUT: "⏱ TIMEOUT", MutationStatus.SURVIVED: "❌ SURVIVED",
                  MutationStatus.EQUIVALENT: "≡ EQUIVALENTE"}.get(m.status, "COMP_ERR")
            mut_str = f"{m.original_snippet} -> {m.mutated_snippet}".replace("|", "&#124;")
            test_str = _quien_lo_mato(m).replace("|", "&#124;")
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
    sanitizers: bool = typer.Option(False, "--sanitizers", help="Compilar y correr con AddressSanitizer: suma los mutantes de reserva de menos (MSR) y sin free (FDR), que solo así se detectan."),
    suite: Optional[Path] = typer.Option(None, "--suite", "-s", exists=True, dir_okay=False, help="Suite de p1_test (prueba.c con su main) que se enlaza con el módulo mutado en lugar de los casos .in/.out; informa la aserción que mató a cada mutante."),
    incluir: List[Path] = typer.Option([], "--incluir", "-I", help="Directorio de headers para compilar con la suite (repetible). Sin -I ni --enlazar se usa el libs/p1_test de la plantilla."),
    enlazar: List[Path] = typer.Option([], "--enlazar", help="Fuente .c o biblioteca .a a enlazar con la suite (repetible), p. ej. libs/p1_test/libp1_test.a."),
    perfil: str = typer.Option("completo", "--perfil", help="Operadores: completo (todos) o catedra (cotas y sentido de los lazos, memoria dinámica y condiciones, en ese orden de prioridad; sin los equivalentes en el listado)."),
    plan_vasquez: Optional[Path] = typer.Option(None, "--plan-vasquez", help=f"Suma los mutantes ECR (sin el chequeo de error de malloc, realloc, fopen…) y escribe en esta ruta (o en <dir>/{NOMBRE_POR_DEFECTO}) el plan de fallos de vasquez para los que sobreviven."),
):
    """Genera mutantes sintéticos del código C y evalúa qué porcentaje es detectado por los tests."""
    from vassili.core.mutator import PERFILES

    if perfil not in PERFILES:
        raise typer.BadParameter(f"usá {' o '.join(PERFILES)}", param_hint="--perfil")
    suite_p1 = resolver_suite(suite, incluir, enlazar) if suite else None
    report = run_mutation_analysis(source_file, tests_dir, timeout=timeout, min_score=min_score, sanitizers=sanitizers,
                                   suite=suite_p1, errores=plan_vasquez is not None, perfil=perfil)
    if plan_vasquez is not None:
        if escribir_plan(report, source_file, plan_vasquez):
            if not json_output:
                console.print(f"[bold green]✓ Plan de fallos para vasquez:[/bold green] {report.plan_vasquez} "
                              f"({len(chequeos_sin_probar(report))} chequeos de error sin probar)")
        elif not json_output:
            console.print("[dim]Plan de vasquez: la suite prueba todos los chequeos de error (o no hay ninguno).[/dim]")

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
    table.add_column("Test que lo Asesinó / qué caso falta", style="blue")

    for m in report.mutants:
        if m.status == MutationStatus.KILLED:
            status_str = "[green]KILLED ✓[/green]"
        elif m.status == MutationStatus.TIMEOUT:
            status_str = "[green]TIMEOUT ⏱[/green]"
        elif m.status == MutationStatus.SURVIVED:
            status_str = "[red]SURVIVED ✗[/red]"
        elif m.status == MutationStatus.EQUIVALENT:
            status_str = "[dim]EQUIVALENTE[/dim]"
        else:
            status_str = "[yellow]COMP_ERR[/yellow]"

        table.add_row(
            str(m.id),
            m.mutation_type,
            str(m.line_number),
            f"{m.original_snippet} ➔ {m.mutated_snippet}",
            status_str,
            _quien_lo_mato(m)
        )

    console.print(table)

    if report.por_operador:
        por_op = Table(title="Por operador", show_header=True, header_style="bold magenta")
        for col in ("Operador", "Generados", "Asesinados", "Sobrevivientes", "Equivalentes", "Score"):
            por_op.add_column(col)
        for fila in _filas_por_operador(report):
            por_op.add_row(*fila)
        console.print(por_op)

    score_color = "green" if report.passed else "red"
    if report.evaluable:
        linea_score = (
            f"[bold {score_color}]Mutation Score Final: {report.mutation_score}%[/bold {score_color}] "
            f"(Mínimo requerido: {min_score}%)"
        )
    else:
        linea_score = f"[bold yellow]Sin score: no evaluable.[/bold yellow] {report.motivo_no_evaluable}"
    console.print(Panel(
        f"[bold]Mutantes Totales:[/bold] {report.total_mutants}\n"
        f"[bold green]Mutantes Asesinados (Killed):[/bold green] {report.killed_count}\n"
        f"[bold red]Mutantes Sobrevivientes (Survived):[/bold red] {report.survived_count}\n"
        f"[dim]Equivalentes (fuera del score):[/dim] {report.equivalent_count}\n"
        f"[dim]Aislamiento:[/dim] {report.aislamiento}\n"
        f"{linea_score}",
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
        tabla.add_row(str(c["componente"]), f"[{color}]{simbolo} {c['estado']}[/{color}]", str(c["detalle"]))

    console.print(tabla)
    if not todo_ok:
        console.print("\n[bold red]Instalá gcc (`sudo apt install gcc` o equivalente).[/bold red]")
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
