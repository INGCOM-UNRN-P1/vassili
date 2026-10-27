"""Ola 12 (QoL #1012–#1016): `--perfil catedra` prioriza cotas de lazos, memoria dinámica y
condiciones relacionales, y descarta del listado los mutantes equivalentes."""

import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from vassili.cli import app
from vassili.core import mutator
from vassili.core.models import MutationStatus
from vassili.core.mutation_runner import run_mutation_analysis
from vassili.core.mutator import generate_mutants_for_file

necesita_gcc = pytest.mark.skipif(not shutil.which("gcc"), reason="requiere gcc")

FUENTE = """int f(int *v, int n)
{
    int s = 0;
    if (!v)
    {
        return -1;
    }
    s = s + n * 2;
    if (n > 3 && v[0] == 1)
    {
        s = s - 1;
    }
    for (int i = 0; i < n - 1; i++)
    {
        s = s + v[i];
    }
    return 0;
}
"""


def _mutantes(tmp_path: Path, perfil: str, **kw):
    ruta = tmp_path / "f.c"
    ruta.write_text(FUENTE, encoding="utf-8")
    return [m for m, _ in generate_mutants_for_file(ruta, perfil=perfil, **kw)]


def test_catedra_deja_lazos_primero_luego_condiciones_y_sin_negaciones_ni_retornos(tmp_path):
    muts = _mutantes(tmp_path, "catedra")
    familias = [(m.line_number, m.mutation_type) for m in muts]
    # Primero la cabecera del for (línea 13): cota, aritmética de la cota y sentido.
    assert familias[:3] == [(13, "ROR"), (13, "AOR"), (13, "UOI")]
    # Después las condiciones de los if; nada de LNR, RVR ni aritmética fuera de un lazo.
    assert set(familias[3:]) == {(9, "ROR"), (9, "LCR")}
    assert not {t for _, t in familias} & {"LNR", "RVR"}
    assert not any(t == "AOR" and linea != 13 for linea, t in familias)
    assert [m.id for m in muts] == list(range(1, len(muts) + 1))


def test_catedra_aplica_el_tope_despues_de_priorizar(tmp_path, monkeypatch):
    monkeypatch.setattr(mutator, "MAX_MUTANTES", 2)
    assert [m.line_number for m in _mutantes(tmp_path, "catedra")] == [13, 13]
    assert [m.line_number for m in _mutantes(tmp_path, "completo")] == [4, 6]


def test_perfil_desconocido(tmp_path):
    with pytest.raises(ValueError):
        _mutantes(tmp_path, "rapido")
    (tmp_path / "f.c").write_text(FUENTE, encoding="utf-8")
    res = CliRunner().invoke(app, ["mutate", str(tmp_path / "f.c"), "--perfil", "rapido"])
    assert res.exit_code == 2


@necesita_gcc
def test_catedra_descarta_los_equivalentes_del_listado_pero_los_cuenta(tmp_path):
    src = tmp_path / "p.c"
    src.write_text(
        "#include <stdio.h>\n"
        "int main(void)\n{\n"
        "    int a = 0;\n"
        "    if (scanf(\"%d\", &a) != 1) return 1;\n"
        "    for (int i = 0; i < a * 1; i++)\n"
        "        printf(\"%d\\n\", i);\n"
        "    return 0;\n}\n",
        encoding="utf-8",
    )
    casos = tmp_path / "casos"
    casos.mkdir()
    (casos / "1.in").write_text("2\n", encoding="utf-8")
    (casos / "1.out").write_text("0\n1\n", encoding="utf-8")

    completo = run_mutation_analysis(src, casos)
    catedra = run_mutation_analysis(src, casos, perfil="catedra")

    assert any(m.status == MutationStatus.EQUIVALENT for m in completo.mutants)
    assert catedra.perfil == "catedra" and catedra.equivalent_count >= 1
    assert not any(m.status == MutationStatus.EQUIVALENT for m in catedra.mutants)
    assert sum(r.equivalentes for r in catedra.por_operador.values()) == catedra.equivalent_count
