"""Generador de mutantes de código fuente en C para VASSILI."""

import re
from pathlib import Path
from typing import Callable, List, Optional, Tuple, Union
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

def _retorno_constante(texto: str) -> str:
    """`return 0;` → `return 1;` y cualquier otra constante → `return 0;` (QoL #1014)."""
    m = re.match(r"return(\s+)(-?\d+)", texto)
    assert m is not None
    return f"return{m.group(1)}{'1' if int(m.group(2)) == 0 else '0'}"


def _argumentos_de(linea: str, nombre: str) -> Optional[Tuple[int, int]]:
    """Posición de los argumentos de la primera llamada `nombre(...)`, con paréntesis balanceados."""
    m = re.search(rf"\b{nombre}\s*\(", linea)
    if not m:
        return None
    nivel = 1
    for i in range(m.end(), len(linea)):
        if linea[i] == "(":
            nivel += 1
        elif linea[i] == ")":
            nivel -= 1
            if nivel == 0:
                return (m.end(), i) if linea[m.end():i].strip() else None
    return None


def _llamada_completa(linea: str, nombre: str) -> Optional[Tuple[int, int]]:
    args = _argumentos_de(linea, nombre)
    if not args:
        return None
    inicio = re.search(rf"\b{nombre}\s*\(", linea)
    assert inicio is not None
    return inicio.start(), args[1] + 1


# Operadores de mutación: (familia, patrón, reemplazo, símbolo). El patrón es una regex o una
# función que devuelve la posición (inicio, fin) a reemplazar; el reemplazo, un texto o una función
# del texto original de esa posición.
Patron = Union[str, Callable[[str], Optional[Tuple[int, int]]]]
Reemplazo = Union[str, Callable[[str], str]]

MUTATION_RULES: List[Tuple[str, Patron, Reemplazo, str]] = [
    # Relacionales (también los bordes de los lazos: `<` → `<=`, QoL #1012)
    ("ROR", r'\s*==\s*', " != ", "=="),
    ("ROR", r'\s*!=\s*', " == ", "!="),
    ("ROR", r'\s*<=\s*', " > ", "<="),
    ("ROR", r'\s*>=\s*', " < ", ">="),
    ("ROR", r'(?<![<=-])\s*<\s*(?![<=-])', " <= ", "<"),
    ("ROR", r'(?<![>=-])\s*>\s*(?![>=-])', " >= ", ">"),
    # Aritméticos
    ("AOR", r'(?<![\+\-])\s*\+\s*(?![\+\-=])', " - ", "+"),
    ("AOR", r'(?<![\+\-])\s*\-\s*(?![\+\-=>])', " + ", "-"),
    ("AOR", r'\s*\*\s*', " / ", "*"),
    # Incremento y decremento: el sentido del lazo (QoL #1012)
    ("UOI", r'\+\+', "--", "++"),
    ("UOI", r'--', "++", "--"),
    # Lógicos (QoL #1013)
    ("LCR", r'\s*&&\s*', " || ", "&&"),
    ("LCR", r'\s*\|\|\s*', " && ", "||"),
    ("LNR", r'!(?!=)', "", "!"),
    # Retorno de constantes (QoL #1014); no en main, donde solo cambia el código de salida
    ("RVR", r'\breturn\s+-?\d+(?=\s*;)', _retorno_constante, "return"),
    # Una posición menos en la reserva (QoL #1015): solo con --sanitizers, que detecta el desborde
    ("MSR", lambda l: _argumentos_de(l, "malloc"), lambda a: f"({a}) - 1", "malloc"),
    # Sin free (QoL #1016): solo con --sanitizers, que es lo único que detecta la fuga
    ("FDR", lambda l: _llamada_completa(l, "free"), "(void)0", "free"),
]

# Familias que solo una corrida con sanitizers puede matar: sin ellos son mutantes inmatables
# que bajarían el score sin que la suite tenga la culpa.
FAMILIAS_CON_SANITIZERS = {"MSR", "FDR"}

_FUNCION_MAIN = re.compile(r"\bmain\s*\(")


def _buscar(patron: Patron, linea: str) -> Optional[Tuple[int, int]]:
    if callable(patron):
        return patron(linea)
    m = re.search(patron, linea)
    return (m.start(), m.end()) if m else None


def generate_mutants_for_file(file_path: Path, sanitizers: bool = False) -> List[Tuple[Mutant, str]]:
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
    nivel = 0
    en_main = False
    dentro_de_main = False  # ya se abrió la llave de main (con estilo Allman va en la línea siguiente)
    for idx, line in enumerate(lines):
        stripped = line.strip()
        linea_busqueda = lines_enmascaradas[idx] if idx < len(lines_enmascaradas) else line
        if nivel == 0 and _FUNCION_MAIN.search(linea_busqueda):
            en_main = True
        nivel += linea_busqueda.count("{") - linea_busqueda.count("}")
        if en_main and nivel > 0:
            dentro_de_main = True
        # Ignorar comentarios o includes
        if stripped.startswith("//") or stripped.startswith("/*") or stripped.startswith("#"):
            continue

        for m_type, pattern, replacement, symbol in MUTATION_RULES:
            if mutant_id > MAX_MUTANTES:
                break
            if m_type in FAMILIAS_CON_SANITIZERS and not sanitizers:
                continue
            if m_type == "RVR" and en_main:
                continue
            pos = _buscar(pattern, linea_busqueda)
            if pos and symbol == "*" and not _es_multiplicacion_binaria(linea_busqueda, pos[0]):
                # Desreferencia o declaración de puntero: no es un operador
                # aritmético y su mutación no compilaría.
                pos = None
            if pos:
                inicio, fin = pos
                nuevo = replacement(line[inicio:fin]) if callable(replacement) else replacement
                # Reemplazar primera ocurrencia en la línea
                mutated_line = line[:inicio] + nuevo + line[fin:]
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

        if dentro_de_main and nivel <= 0:
            en_main = dentro_de_main = False
        # El tope es GLOBAL por archivo. El `break` anterior solo salía del
        # bucle de reglas (12), no del de líneas, así que un archivo con 60
        # operadores generaba 60 mutantes pese al tope declarado de 50.
        if mutant_id > MAX_MUTANTES:
            break

    return mutants_with_code
