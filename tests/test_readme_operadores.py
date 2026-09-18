"""Regresión de VASSILI-D0801: el README declaraba mutación "sobre el AST" y de literales."""

from pathlib import Path

from vassili.core.mutator import MUTATION_RULES

README = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")


def test_el_readme_no_declara_una_tecnica_que_no_existe():
    assert "sobre el AST" not in README
    assert "reemplazo de literales" not in README
    assert "sustitución textual" in README


def test_el_readme_documenta_cada_familia_de_operadores_que_existen():
    familias = {familia for familia, *_ in MUTATION_RULES}
    for familia in familias:
        assert f"`{familia}`" in README, familia


def test_el_readme_no_documenta_familias_que_no_existen():
    familias = {familia for familia, *_ in MUTATION_RULES}
    import re

    documentadas = set(re.findall(r"\*\*`([A-Z]{3})`\*\*", README))
    assert documentadas == familias
