"""Ola 12 (QoL #1269): una suite de p1_test como oráculo, con la aserción que mató a cada mutante
y el resumen por operador."""

import shutil
from pathlib import Path

import pytest

from vassili.core.models import MutationStatus
from vassili.core.mutation_runner import SuiteP1, asercion_de, resolver_suite, run_mutation_analysis

necesita_gcc = pytest.mark.skipif(not shutil.which("gcc"), reason="requiere gcc")

# Un «p1_test» mínimo con el mismo protocolo que treadstone 41b344d en modo -q: la línea P1_FALLO
# de la aserción que falla y P1_CRASH si el test se cae. Así el test no depende de la biblioteca.
MINI_P1 = r"""
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
static const char *actual = "-";
static void crash(int s) { (void)s; fprintf(stderr, "P1_CRASH\t%s\tSIGSEGV\n", actual); exit(1); }
#define ASSERT_INT_EQ(e, a) do { if ((e) != (a)) { \
    fprintf(stderr, "P1_FALLO\t%s\t%s:%d\t%s\n", actual, __FILE__, __LINE__, "ASSERT_INT_EQ(" #e ", " #a ")"); \
    exit(1); } } while (0)
#define RUN_TEST(t) do { actual = #t; signal(SIGSEGV, crash); t(); } while (0)
"""

MODULO = """#include "suma.h"

int suma_hasta(int n)
{
    int s = 0;
    for (int i = 1; i <= n; i++)
    {
        s = s + i;
    }
    return s;
}
"""

PRUEBA = """#include "mini_p1.h"
#include "suma.h"

static void test_suma(void)
{
    ASSERT_INT_EQ(10, suma_hasta(4));
}

int main(void)
{
    RUN_TEST(test_suma);
    return 0;
}
"""


@pytest.fixture
def ejercicio(tmp_path: Path) -> Path:
    (tmp_path / "mini_p1.h").write_text(MINI_P1, encoding="utf-8")
    (tmp_path / "suma.h").write_text("int suma_hasta(int n);\n", encoding="utf-8")
    (tmp_path / "suma.c").write_text(MODULO, encoding="utf-8")
    (tmp_path / "prueba.c").write_text(PRUEBA, encoding="utf-8")
    return tmp_path


def test_asercion_de_lee_la_primera_linea_p1():
    stderr = "ruido\nP1_FALLO\ttest_a\tprueba.c:12\tASSERT_INT_EQ(1, f())\nP1_FALLO\ttest_b\tprueba.c:20\tX\n"
    assert asercion_de(stderr) == ("test_a", "prueba.c:12: ASSERT_INT_EQ(1, f())")
    assert asercion_de("P1_CRASH\ttest_c\tSIGSEGV\n") == ("test_c", "SIGSEGV")
    assert asercion_de("..F\n") == (None, None)  # un p1_test anterior al protocolo


def test_resolver_suite_encuentra_libs_p1_test_de_la_plantilla(tmp_path):
    lib = tmp_path / "libs" / "p1_test"
    (lib / "include").mkdir(parents=True)
    (lib / "include" / "p1_test.h").write_text("", encoding="utf-8")
    (lib / "libp1_test.a").write_bytes(b"!<arch>\n")
    ej = tmp_path / "ejercicios" / "ejercicio1"
    ej.mkdir(parents=True)
    (ej / "prueba.c").write_text("", encoding="utf-8")

    suite = resolver_suite(ej / "prueba.c")

    assert suite.incluir == ((lib / "include").resolve(), lib.resolve())
    assert suite.enlazar == ((lib / "libp1_test.a").resolve(),)


@necesita_gcc
def test_la_suite_mata_mutantes_e_informa_la_asercion(ejercicio):
    suite = SuiteP1(prueba=(ejercicio / "prueba.c").resolve())
    rep = run_mutation_analysis(ejercicio / "suma.c", ejercicio, timeout=2.0, suite=suite)

    assert rep.baseline_ok and rep.suite.endswith("prueba.c")
    borde = next(m for m in rep.mutants if "i > n" in m.mutated_snippet)
    assert borde.status == MutationStatus.KILLED
    assert borde.killing_test == "test_suma"
    assert borde.asercion.startswith("prueba.c:6: ASSERT_INT_EQ(10, suma_hasta(4))")
    # Resumen por operador: cada mutante en su familia, con su score.
    ror = rep.por_operador["ROR"]
    assert ror.generados == sum(1 for m in rep.mutants if m.mutation_type == "ROR")
    assert ror.asesinados >= 1 and ror.score is not None


@necesita_gcc
def test_la_suite_que_falla_sobre_el_original_no_da_score(ejercicio):
    (ejercicio / "prueba.c").write_text(PRUEBA.replace("10, suma_hasta(4)", "11, suma_hasta(4)"), encoding="utf-8")
    rep = run_mutation_analysis(ejercicio / "suma.c", ejercicio, suite=SuiteP1(prueba=ejercicio / "prueba.c"))
    assert not rep.baseline_ok
    assert rep.baseline_fallos and rep.baseline_fallos[0].startswith("test_suma (")
