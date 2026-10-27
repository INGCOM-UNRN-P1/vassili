"""Ola 12 (QoL #1011): cada corrida de un mutante va al sandbox de nostromo, con cuota de tiempo y
memoria, sin comprometer al evaluador."""

import shutil
import subprocess
from pathlib import Path

import pytest

from vassili.core import mutation_runner
from vassili.core.models import MutationStatus
from vassili.core.mutation_runner import AISLAMIENTO_PROPIO, _ejecutar, run_mutation_analysis

necesita_gcc = pytest.mark.skipif(not shutil.which("gcc"), reason="requiere gcc")
nostromo = pytest.importorskip("nostromo.core.sandbox")
con_bwrap = pytest.mark.skipif(
    not (shutil.which("bwrap") and nostromo.bwrap_funciona(shutil.which("bwrap"))),
    reason="requiere bwrap con user namespaces",
)


def _compilar(tmp_path: Path, codigo: str, nombre: str = "prog") -> Path:
    fuente = tmp_path / f"{nombre}.c"
    fuente.write_text(codigo, encoding="utf-8")
    binario = tmp_path / nombre
    subprocess.run(["gcc", str(fuente), "-o", str(binario)], check=True)
    return binario


@necesita_gcc
def test_el_bucle_infinito_se_corta_por_tiempo(tmp_path):
    binario = _compilar(tmp_path, "int main(void) { for (;;) {} }\n")
    with pytest.raises(subprocess.TimeoutExpired):
        _ejecutar(binario, "", 0.5, sanitizers=False)


@necesita_gcc
def test_la_reserva_sin_limite_se_corta_por_memoria_antes_del_timeout(tmp_path):
    binario = _compilar(
        tmp_path,
        "#include <stdlib.h>\n#include <string.h>\n"
        "int main(void) { for (;;) { char *p = malloc(64u << 20); if (!p) return 3; memset(p, 1, 64u << 20); } }\n",
    )
    corrida = _ejecutar(binario, "", 10.0, sanitizers=False)
    assert corrida.retorno != 0
    assert corrida.aislamiento.startswith("nostromo")


@necesita_gcc
@con_bwrap
def test_un_mutante_no_escribe_fuera_del_sandbox(tmp_path):
    canario = tmp_path / "canario.txt"
    binario = _compilar(
        tmp_path,
        "#include <stdio.h>\n"
        f'int main(void) {{ FILE *f = fopen("{canario}", "w"); if (!f) return 4; fputs("x", f); fclose(f); return 0; }}\n',
    )
    corrida = _ejecutar(binario, "", 5.0, sanitizers=False)
    assert corrida.aislamiento == "nostromo (bwrap)"
    assert not canario.exists()
    assert corrida.retorno == 4


@necesita_gcc
def test_el_analisis_informa_el_aislamiento_y_mata_al_mutante_que_rompe_la_memoria(tmp_path):
    fuente = tmp_path / "suma.c"
    fuente.write_text(
        "#include <stdio.h>\n"
        "int main(void)\n{\n"
        "    int v[4] = {1, 2, 3, 4};\n"
        "    int n = 0, s = 0;\n"
        "    if (scanf(\"%d\", &n) != 1) return 1;\n"
        "    for (int i = 0; i < n; i++)\n"
        "        s = s + v[i % 4];\n"
        "    printf(\"%d\\n\", s);\n"
        "    return 0;\n}\n",
        encoding="utf-8",
    )
    suite = tmp_path / "suite"
    suite.mkdir()
    (suite / "1.in").write_text("4\n", encoding="utf-8")
    (suite / "1.out").write_text("10\n", encoding="utf-8")

    rep = run_mutation_analysis(fuente, suite, timeout=1.0)

    assert rep.aislamiento.startswith("nostromo")
    # `i++` → `i--` recorre hacia índices negativos sin fin: lo corta la cuota, no cuelga vassili.
    decremento = next(m for m in rep.mutants if m.mutated_snippet.endswith("i--)"))
    assert decremento.status in (MutationStatus.KILLED, MutationStatus.TIMEOUT)


def test_sin_nostromo_se_usa_el_camino_propio(tmp_path, monkeypatch):
    monkeypatch.setattr(mutation_runner, "_ejecutar_en_nostromo", lambda *a, **k: None)
    if not shutil.which("gcc"):
        pytest.skip("requiere gcc")
    binario = _compilar(tmp_path, '#include <stdio.h>\nint main(void) { puts("hola"); return 0; }\n')
    corrida = _ejecutar(binario, "", 5.0, sanitizers=False)
    assert (corrida.retorno, corrida.stdout, corrida.aislamiento) == (0, "hola\n", AISLAMIENTO_PROPIO)
