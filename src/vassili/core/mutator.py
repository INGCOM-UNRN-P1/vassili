"""Generador de mutantes de código fuente en C para VASSILI."""

import re
from pathlib import Path
from typing import List, Tuple
from vassili.core.models import Mutant, MutationStatus

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

    mutant_id = 1
    for idx, line in enumerate(lines):
        stripped = line.strip()
        # Ignorar comentarios o includes
        if stripped.startswith("//") or stripped.startswith("/*") or stripped.startswith("#"):
            continue

        for m_type, pattern, replacement, symbol in MUTATION_RULES:
            match = re.search(pattern, line)
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

                # Limitar cantidad de mutantes por línea
                if mutant_id > 50:
                    break

    return mutants_with_code
