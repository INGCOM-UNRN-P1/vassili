"""Generador de mutantes de código fuente en C para VASSILI."""

import re
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple, Union
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


# Funciones de biblioteca cuyo fallo un programa de P1 tiene que contemplar (Ola 12): las que
# vasquez sabe hacer fallar y que devuelven NULL al fallar.
FUNCIONES_QUE_FALLAN = ("malloc", "calloc", "realloc", "strdup", "fopen")
_VAR = r"[A-Za-z_]\w*(?:(?:->|\.)[A-Za-z_]\w*)*"
_RE_ASIGNACION = re.compile(rf"(?P<var>{_VAR})\s*=\s*(?:\([^()]*\)\s*)?(?P<fn>{'|'.join(FUNCIONES_QUE_FALLAN)})\s*\(")
_CHEQUEOS_DE_ERROR = [
    re.compile(rf"\bif\s*\(\s*(?P<cond>(?P<var>{_VAR})\s*==\s*(?:NULL|0))\s*\)"),
    re.compile(rf"\bif\s*\(\s*(?P<cond>(?:NULL|0)\s*==\s*(?P<var>{_VAR}))\s*\)"),
    re.compile(rf"\bif\s*\(\s*(?P<cond>!\s*(?P<var>{_VAR}))\s*\)"),
    # La llamada dentro de la condición: if ((f = fopen(ruta, "r")) == NULL)
    re.compile(rf"\bif\s*\(\s*(?P<cond>\(\s*(?P<var>{_VAR})\s*=\s*(?P<fn>{'|'.join(FUNCIONES_QUE_FALLAN)})\s*\(.*\)\s*\)"
               rf"\s*==\s*(?:NULL|0))\s*\)"),
]


def chequeo_de_error(linea: str) -> Optional[re.Match]:
    """El `if` que verifica si un puntero es NULL (la condición queda en el grupo `cond`)."""
    for patron in _CHEQUEOS_DE_ERROR:
        m = patron.search(linea)
        if m:
            return m
    return None


def _condicion_de_error(linea: str) -> Optional[Tuple[int, int]]:
    m = chequeo_de_error(linea)
    return m.span("cond") if m else None


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
    # Sin el chequeo de error de malloc, realloc, fopen… (Ola 12): solo con `errores`; si el mutante
    # sobrevive, la suite nunca recorre ese camino y la función va al plan de vasquez.
    ("ECR", _condicion_de_error, lambda c: f"({c}) && 0", "if"),
]

# Familias que solo una corrida con sanitizers puede matar: sin ellos son mutantes inmatables
# que bajarían el score sin que la suite tenga la culpa.
FAMILIAS_CON_SANITIZERS = {"MSR", "FDR"}
# Familias que miden si la suite recorre los caminos de error, no su calidad sobre el camino normal:
# con casos .in/.out ningún caso puede hacer fallar malloc, así que quedan fuera del score.
FAMILIAS_DE_ERRORES = {"ECR"}

_FUNCION_MAIN = re.compile(r"\bmain\s*\(")

# Perfiles de operadores (QoL #1012–#1016). `catedra` deja los que más enseñan en P1, en este orden
# de prioridad (el tope de mutantes se aplica después de ordenar): las cotas y el sentido de los
# lazos, la memoria dinámica y las condiciones de los if; no muta negaciones sueltas ni retornos
# constantes, ni aritmética fuera de la cabecera de un lazo.
PERFILES = ("completo", "catedra")
_RE_LAZO = re.compile(r"\b(?:for|while)\s*\(")
_RE_CABECERA_FOR = re.compile(r"\bfor\s*\(")
_RE_CONDICION = re.compile(r"\bif\s*\(|\?")
_FAMILIAS_DE_MEMORIA = {"MSR", "FDR", "ECR"}


def prioridad_catedra(familia: str, linea: str) -> Optional[int]:
    """0 = cota o sentido de un lazo, 1 = memoria dinámica, 2 = condición; None = fuera del perfil."""
    if familia in _FAMILIAS_DE_MEMORIA:
        return 1
    if familia in ("ROR", "LCR"):
        if _RE_LAZO.search(linea):
            return 0
        return 2 if _RE_CONDICION.search(linea) else None
    if familia == "UOI":
        return 0 if _RE_CABECERA_FOR.search(linea) else None
    if familia == "AOR":
        return 0 if _RE_LAZO.search(linea) else None
    return None


def _buscar(patron: Patron, linea: str) -> Optional[Tuple[int, int]]:
    if callable(patron):
        return patron(linea)
    m = re.search(patron, linea)
    return (m.start(), m.end()) if m else None


def generate_mutants_for_file(file_path: Path, sanitizers: bool = False,
                              errores: bool = False, perfil: str = "completo") -> List[Tuple[Mutant, str]]:
    """Genera lista de mutantes y el código fuente C completo de cada mutante."""
    if perfil not in PERFILES:
        raise ValueError(f"perfil desconocido: {perfil} (usá {' o '.join(PERFILES)})")
    # Con `catedra` se generan todos los candidatos, se ordenan por prioridad y recién ahí se corta.
    tope = MAX_MUTANTES if perfil == "completo" else MAX_MUTANTES * 20
    prioridades: Dict[int, int] = {}
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
    # Variable → (función, línea) de la última asignación desde malloc, fopen… en la función actual.
    asignaciones: Dict[str, Tuple[str, int]] = {}
    en_main = False
    dentro_de_main = False  # ya se abrió la llave de main (con estilo Allman va en la línea siguiente)
    for idx, line in enumerate(lines):
        stripped = line.strip()
        linea_busqueda = lines_enmascaradas[idx] if idx < len(lines_enmascaradas) else line
        if nivel == 0 and _FUNCION_MAIN.search(linea_busqueda):
            en_main = True
        for asignacion in _RE_ASIGNACION.finditer(linea_busqueda):
            asignaciones[asignacion["var"]] = (asignacion["fn"], idx + 1)
        nivel += linea_busqueda.count("{") - linea_busqueda.count("}")
        if en_main and nivel > 0:
            dentro_de_main = True
        # Ignorar comentarios o includes
        if stripped.startswith("//") or stripped.startswith("/*") or stripped.startswith("#"):
            continue

        for m_type, pattern, replacement, symbol in MUTATION_RULES:
            if mutant_id > tope:
                break
            prioridad = prioridad_catedra(m_type, linea_busqueda) if perfil == "catedra" else 0
            if prioridad is None:
                continue
            if m_type in FAMILIAS_CON_SANITIZERS and not sanitizers:
                continue
            if m_type in FAMILIAS_DE_ERRORES and not errores:
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
                funcion: Optional[Tuple[str, int]] = None
                if m_type == "ECR":
                    chequeo = chequeo_de_error(linea_busqueda)
                    assert chequeo is not None
                    funcion = ((chequeo["fn"], idx + 1) if chequeo.groupdict().get("fn")
                               else asignaciones.get(chequeo["var"]))
                    if funcion is None:
                        continue  # el puntero no viene de una función que pueda fallar
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
                    status=MutationStatus.SURVIVED,
                    funcion=funcion[0] if funcion else None,
                    linea_llamada=funcion[1] if funcion else None,
                )
                mutants_with_code.append((m, mutated_code))
                prioridades[m.id] = prioridad
                mutant_id += 1

        if dentro_de_main and nivel <= 0:
            en_main = dentro_de_main = False
        if nivel <= 0:
            asignaciones.clear()
        # El tope es GLOBAL por archivo. El `break` anterior solo salía del
        # bucle de reglas (12), no del de líneas, así que un archivo con 60
        # operadores generaba 60 mutantes pese al tope declarado de 50.
        if mutant_id > tope:
            break

    if perfil == "catedra":
        mutants_with_code.sort(key=lambda par: (prioridades[par[0].id], par[0].id))
        mutants_with_code = mutants_with_code[:MAX_MUTANTES]
        for nuevo_id, (m, _) in enumerate(mutants_with_code, 1):
            m.id = nuevo_id
    return mutants_with_code
