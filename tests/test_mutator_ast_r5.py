"""Pruebas del mutador AST Tree-sitter (ola R5) en vassili."""

from __future__ import annotations

from pathlib import Path

from vassili.core.mutator import generate_mutants_for_file


def test_mutador_ast_ignora_if0_y_punteros_en_expresiones_complejas(tmp_path: Path):
    src = tmp_path / "ast_case.c"
    src.write_text(
        "#if 0\n"
        "int muerto(int a, int b) { return a == b; }\n"
        "#endif\n"
        "int vivo(int *p, int n) {\n"
        "    int x = *p;\n"
        "    return x * n;\n"
        "}\n",
        encoding="utf-8",
    )
    muts = [m for m, _ in generate_mutants_for_file(src)]
    assert [m.line_number for m in muts] == [6]
    assert muts[0].mutation_type == "AOR"
    assert muts[0].mutated_snippet == "return x / n;"
