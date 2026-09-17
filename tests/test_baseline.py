"""Regresión de VASSILI-D0301: sin baseline, una suite rota sacaba 100.

El runner nunca ejecutaba el programa sin mutar. Si la suite ya fallaba sobre
el original —por ejemplo con un `.out` equivocado— todo mutante también
divergía, se lo contaba como asesinado y el score daba 100 con `passed=True`:
la herramienta premiaba exactamente el escenario que debe atrapar.
"""

import shutil
from pathlib import Path

import pytest

from vassili.core.mutation_runner import run_mutation_analysis, verificar_baseline

PROGRAMA = """#include <stdio.h>
int main(void) {
    int a, b;
    if (scanf("%d %d", &a, &b) != 2) return 1;
    printf("%d\\n", a > b ? a : b);
    return 0;
}
"""

necesita_gcc = pytest.mark.skipif(not shutil.which("gcc"), reason="requiere gcc")


@pytest.fixture
def fuente(tmp_path):
    ruta = tmp_path / "prog.c"
    ruta.write_text(PROGRAMA, encoding="utf-8")
    return ruta


def _suite(tmp_path: Path, nombre: str, salida_esperada: str) -> Path:
    d = tmp_path / nombre
    d.mkdir()
    (d / "01.in").write_text("3 7\n", encoding="utf-8")
    (d / "01.out").write_text(salida_esperada, encoding="utf-8")
    return d


@necesita_gcc
def test_suite_rota_no_puede_sacar_puntaje(fuente, tmp_path):
    rota = _suite(tmp_path, "rota", "99\n")  # el máximo de 3 y 7 no es 99
    reporte = run_mutation_analysis(fuente, rota)

    assert reporte.baseline_ok is False
    assert reporte.passed is False
    assert reporte.mutation_score == 0.0
    assert "01.in" in reporte.baseline_fallos


@necesita_gcc
def test_suite_correcta_computa_score_real(fuente, tmp_path):
    buena = _suite(tmp_path, "buena", "7\n")
    reporte = run_mutation_analysis(fuente, buena)

    assert reporte.baseline_ok is True
    assert reporte.baseline_fallos == []
    assert reporte.total_mutants > 0


@necesita_gcc
def test_verificar_baseline_distingue_las_dos_suites(fuente, tmp_path):
    rota = _suite(tmp_path, "rota", "99\n")
    buena = _suite(tmp_path, "buena", "7\n")

    ok_rota, fallos_rota = verificar_baseline(fuente, sorted(rota.glob("*.in")), 2.0)
    ok_buena, fallos_buena = verificar_baseline(fuente, sorted(buena.glob("*.in")), 2.0)

    assert (ok_rota, fallos_rota) == (False, ["01.in"])
    assert (ok_buena, fallos_buena) == (True, [])


@necesita_gcc
def test_programa_que_no_compila_no_pasa_el_baseline(tmp_path):
    malo = tmp_path / "malo.c"
    malo.write_text("int main(void) { return", encoding="utf-8")
    ok, fallos = verificar_baseline(malo, [], 2.0)
    assert ok is False
    assert fallos == ["el programa original no compila"]
