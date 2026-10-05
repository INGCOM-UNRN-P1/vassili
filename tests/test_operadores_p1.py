"""Operadores de P1, equivalentes, aislamiento y sugerencias (QoL #1008, #1009, #1011–#1016)."""

import shutil
from pathlib import Path

import pytest

from vassili.core.models import MutationStatus
from vassili.core.mutation_runner import SUGERENCIAS, _ejecutar, run_mutation_analysis
from vassili.core.mutator import generate_mutants_for_file

necesita_gcc = pytest.mark.skipif(not shutil.which("gcc"), reason="requiere gcc")


def _mutantes(tmp_path: Path, fuente: str, sanitizers: bool = False):
    ruta = tmp_path / "prog.c"
    ruta.write_text(fuente, encoding="utf-8")
    return [(m.mutation_type, m.mutated_snippet) for m, _ in generate_mutants_for_file(ruta, sanitizers=sanitizers)]


def test_incremento_y_negacion(tmp_path):
    muts = _mutantes(tmp_path, "void f(int n)\n{\n    for (int i = 0; i < n; i++) { g(!h(i)); }\n}\n")
    assert ("UOI", "for (int i = 0; i < n; i--) { g(!h(i)); }") in muts
    assert ("LNR", "for (int i = 0; i < n; i++) { g(h(i)); }") in muts
    assert ("ROR", "for (int i = 0; i <= n; i++) { g(!h(i)); }") in muts


def test_retorno_de_constantes_salvo_en_main(tmp_path):
    muts = _mutantes(tmp_path, "int f(void)\n{\n    return 0;\n}\nint g(void) { return -1; }\n"
                               "int main(void)\n{\n    return 0;\n}\n")
    rvr = [s for t, s in muts if t == "RVR"]
    assert rvr == ["return 1;", "int g(void) { return 0; }"]


def test_reserva_de_menos_y_sin_free_solo_con_sanitizers(tmp_path):
    fuente = "void f(int n)\n{\n    int *p = malloc(sizeof(int) * n);\n    free(p);\n}\n"
    assert not [t for t, _ in _mutantes(tmp_path, fuente) if t in ("MSR", "FDR")]
    muts = _mutantes(tmp_path, fuente, sanitizers=True)
    assert ("MSR", "int *p = malloc((sizeof(int) * n) - 1);") in muts
    assert ("FDR", "(void)0;") in muts


def test_el_readme_y_las_sugerencias_cubren_todas_las_familias():
    from vassili.core.mutator import MUTATION_RULES

    assert {familia for familia, *_ in MUTATION_RULES} == set(SUGERENCIAS)


@necesita_gcc
@pytest.mark.skipif(not hasattr(__import__("os"), "fork"), reason="límites POSIX")
def test_la_salida_infinita_se_corta_sin_agotar_la_memoria(tmp_path):
    fuente = tmp_path / "loco.c"
    fuente.write_text('#include <stdio.h>\nint main(void) { for (;;) puts("xxxxxxxxxxxxxxxx"); }\n', encoding="utf-8")
    binario = tmp_path / "loco"
    import subprocess

    subprocess.run(["gcc", str(fuente), "-o", str(binario)], check=True)
    try:
        ret, salida = _ejecutar(binario, "", 5.0, sanitizers=False)
    except subprocess.TimeoutExpired:
        pytest.fail("el límite de tamaño de salida tenía que cortarlo antes del timeout")
    assert ret != 0 and len(salida) <= 8 * 1024 * 1024


@necesita_gcc
def test_mutante_equivalente_fuera_del_score_y_sugerencia_del_sobreviviente(tmp_path):
    # `x * 1` → `x / 1` genera el mismo código optimizado: equivalente.
    # `a > 10` sin un caso en el borde: ROR sobrevive y sugiere el caso que falta.
    src = tmp_path / "p.c"
    src.write_text(
        "#include <stdio.h>\n"
        "int main(void)\n{\n"
        "    int a = 0;\n"
        "    if (scanf(\"%d\", &a) != 1) return 1;\n"
        "    int b = a * 1;\n"
        "    printf(\"%d\\n\", a > 10 ? b : 0);\n"
        "    return 0;\n}\n",
        encoding="utf-8",
    )
    suite = tmp_path / "suite"
    suite.mkdir()
    (suite / "1.in").write_text("50\n", encoding="utf-8")
    (suite / "1.out").write_text("50\n", encoding="utf-8")
    (suite / "2.in").write_text("3\n", encoding="utf-8")
    (suite / "2.out").write_text("0\n", encoding="utf-8")
    reporte = run_mutation_analysis(src, suite, timeout=2.0)
    por_estado = {m.mutated_snippet: m for m in reporte.mutants}
    assert por_estado["int b = a / 1;"].status == MutationStatus.EQUIVALENT
    assert reporte.equivalent_count >= 1
    vivo = por_estado['printf("%d\\n", a >= 10 ? b : 0);']
    assert vivo.status == MutationStatus.SURVIVED and "borde" in vivo.sugerencia
    validos = reporte.killed_count + reporte.survived_count
    assert reporte.mutation_score == round(reporte.killed_count / validos * 100, 2)
