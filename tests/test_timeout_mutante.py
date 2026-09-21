"""Regresión de VASSILI-D0201: `MutationStatus.TIMEOUT` nunca se asignaba."""

import shutil

import pytest

from vassili.core.models import MutationStatus
from vassili.core.mutation_runner import run_mutation_analysis

PROGRAMA = """#include <stdio.h>
int main(void) {
    int n, i = 0, s = 0;
    if (scanf("%d", &n) != 1) return 1;
    while (i < n) {
        s = s + i;
        i = i + 1;
    }
    printf("%d\\n", s);
    return 0;
}
"""

necesita_gcc = pytest.mark.skipif(not shutil.which("gcc"), reason="requiere gcc")


@necesita_gcc
def test_un_mutante_que_cuelga_se_marca_timeout_y_cuenta_como_asesinado(tmp_path):
    src = tmp_path / "p.c"
    src.write_text(PROGRAMA, encoding="utf-8")
    suite = tmp_path / "suite"
    suite.mkdir()
    (suite / "01.in").write_text("4\n", encoding="utf-8")
    (suite / "01.out").write_text("6\n", encoding="utf-8")

    rep = run_mutation_analysis(src, suite, timeout=0.5)

    tos = [m for m in rep.mutants if m.status == MutationStatus.TIMEOUT]
    assert tos, [(m.mutated_snippet, m.status) for m in rep.mutants]
    assert rep.timeout_count == len(tos)
    assert rep.killed_count >= len(tos)
    assert all("(timeout)" in m.killing_test for m in tos)
