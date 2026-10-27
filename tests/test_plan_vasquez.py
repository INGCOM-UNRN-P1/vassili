"""Ola 12 (QoL #1000, #1009): los chequeos de error que la suite no prueba (mutantes ECR que
sobreviven) se convierten en un plan de fallos para vasquez."""

import shutil
from pathlib import Path

import pytest

from vassili.core.models import MutationStatus
from vassili.core.mutation_runner import run_mutation_analysis
from vassili.core.mutator import generate_mutants_for_file
from vassili.core.plan_vasquez import NOMBRE_POR_DEFECTO, escribir_plan, generar_plan

necesita_gcc = pytest.mark.skipif(not shutil.which("gcc"), reason="requiere gcc")

PROGRAMA = """#include <stdio.h>
#include <stdlib.h>

int main(void)
{
    int n = 0;
    if (scanf("%d", &n) != 1)
    {
        return 1;
    }
    int *v = malloc((size_t)n * sizeof(int));
    if (v == NULL)
    {
        return 2;
    }
    FILE *f;
    if ((f = fopen("/dev/null", "w")) == NULL)
    {
        free(v);
        return 3;
    }
    int *otro = v;
    if (!otro)
    {
        return 4;
    }
    for (int i = 0; i < n; i++)
    {
        v[i] = i;
    }
    fclose(f);
    printf("%d\\n", v[n - 1]);
    free(v);
    return 0;
}
"""


@pytest.fixture
def programa(tmp_path: Path) -> Path:
    fuente = tmp_path / "prog.c"
    fuente.write_text(PROGRAMA, encoding="utf-8")
    casos = tmp_path / "casos"
    casos.mkdir()
    (casos / "1.in").write_text("3\n", encoding="utf-8")
    (casos / "1.out").write_text("2\n", encoding="utf-8")
    return fuente


def _ecr(fuente: Path, errores: bool = True):
    return [m for m, _ in generate_mutants_for_file(fuente, errores=errores) if m.mutation_type == "ECR"]


def test_ecr_solo_en_chequeos_de_punteros_que_vienen_de_una_funcion_que_falla(programa):
    ecr = _ecr(programa)
    assert [(m.line_number, m.funcion, m.linea_llamada) for m in ecr] == [(12, "malloc", 11), (17, "fopen", 17)]
    assert ecr[0].mutated_snippet == "if ((v == NULL) && 0)"
    # La asignación dentro de la condición se conserva: el mutante sólo anula la rama de error.
    assert ecr[1].mutated_snippet == 'if (((f = fopen("/dev/null", "w")) == NULL) && 0)'
    assert _ecr(programa, errores=False) == []


@necesita_gcc
def test_los_chequeos_sin_probar_quedan_fuera_del_score_y_van_al_plan(programa, tmp_path):
    sin = run_mutation_analysis(programa, tmp_path / "casos")
    con = run_mutation_analysis(programa, tmp_path / "casos", errores=True)

    ecr = [m for m in con.mutants if m.mutation_type == "ECR"]
    assert ecr and all(m.status == MutationStatus.SURVIVED and "vasquez" in m.sugerencia for m in ecr)
    assert con.mutation_score == sin.mutation_score  # fuera del score
    assert con.por_operador["ECR"].sobrevivientes == len(ecr)

    plan = generar_plan(con, programa)
    assert plan == {
        "escenarios": [
            {"tipo": "malloc", "llamada": 1},
            {"tipo": "fopen", "llamada": 1, "errno": "ENOENT"},
            {"tipo": "fopen", "llamada": 1, "errno": "EACCES"},
        ],
        "opciones": {"fugas": True},
    }
    assert escribir_plan(con, programa, tmp_path)
    escrito = tmp_path / NOMBRE_POR_DEFECTO
    assert con.plan_vasquez == str(escrito)
    texto = escrito.read_text(encoding="utf-8")
    assert "línea 12: if (v == NULL)  (malloc, línea 11)" in texto
    yaml = pytest.importorskip("yaml")
    assert yaml.safe_load(texto) == plan


def test_sin_chequeos_sin_probar_no_hay_plan(tmp_path):
    from vassili.core.models import MutationReport

    rep = MutationReport(source_file="x.c")
    assert generar_plan(rep, tmp_path / "x.c") is None
    assert not escribir_plan(rep, tmp_path / "x.c", tmp_path)
    assert not (tmp_path / NOMBRE_POR_DEFECTO).exists()
