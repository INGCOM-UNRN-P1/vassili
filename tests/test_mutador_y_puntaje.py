"""Regresión de VASSILI-D0302/D0303/D0304.

D0302: se generaban mutantes DENTRO de literales de cadena (`printf("a == b")`
→ `printf("a != b")`), triviales de matar, que inflaban el score.
D0303: con 0 mutantes válidos el score daba 100 y `passed=True`; la causa
inmediata era la regla `*`→`/` sin guardas, que convertía `*p = 7` en
`/p = 7` (no compila, se descartaba del denominador).
D0304: el tope de 50 mutantes se rompía; el `break` solo salía del bucle de
reglas y no del de líneas.
"""

import shutil
from pathlib import Path

import pytest

from vassili.core.models import MutationReport
from vassili.core.mutation_runner import run_mutation_analysis
from vassili.core.mutator import MAX_MUTANTES, generate_mutants_for_file

necesita_gcc = pytest.mark.skipif(not shutil.which("gcc"), reason="requiere gcc")


def _mutantes(tmp_path: Path, fuente: str):
    ruta = tmp_path / "prog.c"
    ruta.write_text(fuente, encoding="utf-8")
    return [m for m, _ in generate_mutants_for_file(ruta)]


def test_no_se_mutan_operadores_dentro_de_literales(tmp_path):
    mutantes = _mutantes(tmp_path, 'int main(void) { puts("a == b y c && d"); return 0; }\n')
    assert mutantes == []


def test_no_se_mutan_operadores_dentro_de_comentarios_de_bloque_multilinea(tmp_path):
    mutantes = _mutantes(tmp_path, "/* uno\n a == b\n dos */\nint main(void) { return 0; }\n")
    assert mutantes == []


def test_un_operador_real_junto_a_un_literal_si_se_muta(tmp_path):
    mutantes = _mutantes(tmp_path, 'int f(int a, int b) { puts("x == y"); return a == b; }\n')
    assert len(mutantes) == 1
    assert mutantes[0].mutation_type == "ROR"


@pytest.mark.parametrize(
    "linea",
    ["int *p = &a;", "*p = 7;", "return *p;", "x = *q + 1;", "int f(int *p, char *s);"],
)
def test_el_asterisco_de_puntero_no_se_muta_a_division(tmp_path, linea):
    mutantes = _mutantes(tmp_path, f"void f(void) {{ {linea} }}\n")
    assert [m for m in mutantes if "/" in m.mutated_snippet and "/" not in m.original_snippet] == []


def test_la_multiplicacion_binaria_si_se_muta(tmp_path):
    mutantes = _mutantes(tmp_path, "int f(int a, int b) { return a * b; }\n")
    assert len(mutantes) == 1
    assert "/" in mutantes[0].mutated_snippet


def test_el_tope_de_mutantes_es_global(tmp_path):
    lineas = "\n".join(f"    r += a == b;" for _ in range(80))
    mutantes = _mutantes(tmp_path, f"int f(int a, int b) {{ int r = 0;\n{lineas}\n return r; }}\n")
    assert len(mutantes) == MAX_MUTANTES


@necesita_gcc
def test_sin_operadores_mutables_no_se_inventa_un_cien(tmp_path):
    ruta = tmp_path / "vacio.c"
    ruta.write_text("int main(void) { return 0; }\n", encoding="utf-8")
    casos = tmp_path / "tests"
    casos.mkdir()
    reporte = run_mutation_analysis(ruta, casos)
    assert reporte.evaluable is False
    assert reporte.mutation_score == 0.0
    assert "operadores mutables" in reporte.motivo_no_evaluable


def test_el_modelo_expone_evaluable_por_defecto():
    assert MutationReport(source_file="x.c").evaluable is True
