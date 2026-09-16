"""Tests unitarios y de integración para VASSILI."""

from pathlib import Path
from typer.testing import CliRunner
from vassili.cli import app
from vassili.core.mutator import generate_mutants_for_file
from vassili.core.mutation_runner import run_mutation_analysis
from vassili.plugins.ripley_plugin import VassiliPlugin

runner = CliRunner()


def test_generate_mutants_operators(tmp_path):
    c = tmp_path / "calc.c"
    c.write_text("""
    int suma(int a, int b) {
        if (a == b) {
            return a + b;
        }
        return a * b;
    }
    """)
    mutants = generate_mutants_for_file(c)
    assert len(mutants) >= 2
    types = [m[0].mutation_type for m in mutants]
    assert "ROR" in types or "AOR" in types


def test_run_mutation_analysis_kills_mutants(tmp_path):
    src = tmp_path / "app.c"
    src.write_text("""
    #include <stdio.h>
    int main(void) {
        int x;
        if (scanf("%d", &x) == 1) {
            if (x > 0) {
                printf("POSITIVO\\n");
            } else {
                printf("NEGATIVO\\n");
            }
        }
        return 0;
    }
    """)

    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "01.in").write_text("5\n")
    (tests_dir / "01.out").write_text("POSITIVO\n")
    (tests_dir / "02.in").write_text("-3\n")
    (tests_dir / "02.out").write_text("NEGATIVO\n")

    report = run_mutation_analysis(src, tests_dir)
    assert report.total_mutants > 0
    assert report.killed_count > 0


def test_cli_mutate_json(tmp_path):
    src = tmp_path / "app.c"
    src.write_text("int main(void) { return 0; }")
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "01.in").write_text("\n")
    (tests_dir / "01.out").write_text("")

    res = runner.invoke(app, ["mutate", str(src), "-t", str(tests_dir), "--json"])
    assert res.exit_code == 0
    assert '"mutation_score"' in res.output


def test_cli_version():
    res = runner.invoke(app, ["version"])
    assert res.exit_code == 0
    assert "VASSILI" in res.output


def test_ripley_plugin(tmp_path):
    plugin = VassiliPlugin()
    res = plugin.run({"source_dir": str(tmp_path)})
    assert res["passed"] is True


def test_cli_doctor():
    res = runner.invoke(app, ["doctor"])
    assert res.exit_code == 0
    assert "Diagnóstico del Entorno VASSILI" in res.output

    res_json = runner.invoke(app, ["doctor", "--json"])
    assert res_json.exit_code == 0
    assert '"schema_version": "1.0.0"' in res_json.output
    assert '"herramienta": "vassili"' in res_json.output
    assert '"ok": true' in res_json.output

