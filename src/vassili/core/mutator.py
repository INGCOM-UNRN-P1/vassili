"""Generador de mutantes de código fuente en C para VASSILI."""

import re
from pathlib import Path
from typing import List, Tuple
from vassili.core.masking import enmascarar_comentarios_y_literales
from vassili.core.models import Mutant, MutationStatus

# Tope global de mutantes por archivo.
MAX_MUTANTES = 50

# Palabras tras las cuales un `*` NO es una multiplicación: declara un puntero
# (`int *p`) o es una desreferencia (`return *p`). Mutarlo a `/` produce código
# que no compila, y esos mutantes inválidos se descartaban del denominador.
_ANTES_DE_ASTERISCO_NO_BINARIO = re.compile(
    r"(?:\b(?:int|char|short|long|float|double|unsigned|signed|void|const|struct|"
    r"return|sizeof|size_t|FILE|\w+_t)|[=,;{(!<>+\-*/%&|?:])\s*$"
)


def _es_multiplicacion_binaria(linea: str, inicio: int) -> bool:
    """`*` es binario si lo que lo precede es un operando (identificador, número, `)` o `]`)."""
    antes = linea[:inicio]
    if not antes.strip():
        return False
    return _ANTES_DE_ASTERISCO_NO_BINARIO.search(antes) is None

# Operadores de mutación clásicos
MUTATION_RULES = [
    # Relacionales
    ("ROR", r'\s*==\s*', " != ", "=="),
    ("ROR", r'\s*!=\s*', " == ", "!="),
    ("ROR", r'\s*<=\s*', " > ", "<="),
    ("ROR", r'\s*>=\s*', " < ", ">="),
    ("ROR", r'(?<![<=-])\s*<\s*(?![<=-])', " <= ", "<"),
    ("ROR", r'(?<![>=-])\s*>\s*(?![>=-])', " >= ", ">"),
    # Aritméticos
    ("AOR", r'(?<![\+\-])\s*\+\s*(?![\+\-])', " - ", "+"),
    ("AOR", r'(?<![\+\-])\s*\-\s*(?![\+\-])', " + ", "-"),
    ("AOR", r'\s*\*\s*', " / ", "*"),
    # Lógicos
    ("LCR", r'\s*&&\s*', " || ", "&&"),
    ("LCR", r'\s*\|\|\s*', " && ", "||"),
]


def generate_mutants_for_file(file_path: Path) -> List[Tuple[Mutant, str]]:
    """Genera lista de mutantes y el código fuente C completo de cada mutante."""
    mutants_with_code: List[Tuple[Mutant, str]] = []
    content = file_path.read_text(encoding="utf-8", errors="replace")
    lines = content.splitlines()
    # Se busca el operador en una copia con los comentarios y literales
    # blanqueados (mismas posiciones y líneas) y se aplica el reemplazo sobre la
    # línea ORIGINAL: así no se mutan operadores que viven dentro de un string
    # (`printf("a == b")`) o de un comentario, incluidos los de bloque que abarcan
    # varias líneas y los que siguen a código en la misma línea.
    lines_enmascaradas = enmascarar_comentarios_y_literales(content).splitlines()

    mutant_id = 1
    for idx, line in enumerate(lines):
        stripped = line.strip()
        # Ignorar comentarios o includes
        if stripped.startswith("//") or stripped.startswith("/*") or stripped.startswith("#"):
            continue
        linea_busqueda = lines_enmascaradas[idx] if idx < len(lines_enmascaradas) else line

        for m_type, pattern, replacement, symbol in MUTATION_RULES:
            if mutant_id > MAX_MUTANTES:
                break
            match = re.search(pattern, linea_busqueda)
            if match and symbol == "*" and not _es_multiplicacion_binaria(linea_busqueda, match.start()):
                # Desreferencia o declaración de puntero: no es un operador
                # aritmético y su mutación no compilaría.
                match = None
            if match:
                # Reemplazar primera ocurrencia en la línea
                mutated_line = line[:match.start()] + replacement + line[match.end():]
                mutated_lines = list(lines)
                mutated_lines[idx] = mutated_line
                mutated_code = "\n".join(mutated_lines)

                m = Mutant(
                    id=mutant_id,
                    file_path=str(file_path),
                    line_number=idx + 1,
                    original_snippet=stripped,
                    mutated_snippet=mutated_line.strip(),
                    mutation_type=m_type,
                    status=MutationStatus.SURVIVED
                )
                mutants_with_code.append((m, mutated_code))
                mutant_id += 1

        # El tope es GLOBAL por archivo. El `break` anterior solo salía del
        # bucle de reglas (12), no del de líneas, así que un archivo con 60
        # operadores generaba 60 mutantes pese al tope declarado de 50.
        if mutant_id > MAX_MUTANTES:
            break

    return mutants_with_code
