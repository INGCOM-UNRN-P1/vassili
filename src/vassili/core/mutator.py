"""Generador de mutantes de código fuente en C para VASSILI."""

import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union
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


_BINARIOS_AST: Dict[str, Tuple[int, str, str]] = {
    "==": (0, "ROR", " != "),
    "!=": (1, "ROR", " == "),
    "<=": (2, "ROR", " > "),
    ">=": (3, "ROR", " < "),
    "<": (4, "ROR", " <= "),
    ">": (5, "ROR", " >= "),
    "+": (6, "AOR", " - "),
    "-": (7, "AOR", " + "),
    "*": (8, "AOR", " / "),
    "&&": (11, "LCR", " || "),
    "||": (12, "LCR", " && "),
}
_UNARIOS_INC_AST: Dict[str, Tuple[int, str, str]] = {
    "++": (9, "UOI", "--"),
    "--": (10, "UOI", "++"),
}


def _nombre_funcion_def(node) -> str:
    declarator = node.child_by_field_name("declarator")
    while declarator is not None:
        if declarator.type == "identifier":
            return (declarator.text or b"").decode("utf-8", errors="replace")
        sub = declarator.child_by_field_name("declarator")
        if sub is not None:
            declarator = sub
        else:
            break
    return ""


def _extraer_llamada_falla(expr_node) -> Optional[str]:
    """Devuelve el nombre de función en `FUNCIONES_QUE_FALLAN` si `expr_node` (o su cast) la llama."""
    actual = expr_node
    while actual is not None and actual.type in ("cast_expression", "parenthesized_expression"):
        actual = actual.child_by_field_name("value") or next(
            (c for c in actual.children if c.is_named and c.type != "type_descriptor"),
            None,
        )
    if actual is not None and actual.type == "call_expression":
        fn = actual.child_by_field_name("function")
        if fn is not None and fn.type == "identifier":
            nombre = (fn.text or b"").decode("utf-8", errors="replace")
            if nombre in FUNCIONES_QUE_FALLAN:
                return nombre
    return None


def _generate_mutants_ast(
    content: str,
    file_path: Path,
    sanitizers: bool,
    errores: bool,
    perfil: str,
    tope: int,
) -> Optional[List[Tuple[Mutant, str]]]:
    """Genera mutantes usando los rangos exactos de nodos del AST Tree-sitter."""
    try:
        from yutani.ts_queries import enmascarar_bloques_inactivos, parser_c
    except ImportError:
        return None

    masked = enmascarar_bloques_inactivos(content)
    orig_lines = content.splitlines()
    masked_lines = masked.splitlines()
    lineas_inactivas = {
        idx for idx, (o, m) in enumerate(zip(orig_lines, masked_lines, strict=False)) if o != m
    }

    source_bytes = content.encode("utf-8")
    tree = parser_c().parse(source_bytes)
    lines = orig_lines

    # candidatos[(line_idx, rule_idx)] = (start_byte, end_byte, familia, replacement, funcion_ecr)
    candidatos: Dict[Tuple[int, int], Tuple[int, int, str, str, Optional[Tuple[str, int]]]] = {}
    asignaciones_por_fn: Dict[str, Tuple[str, int]] = {}

    def _registrar(
        line_idx: int,
        rule_idx: int,
        start_b: int,
        end_b: int,
        familia: str,
        nuevo: str,
        funcion_ecr: Optional[Tuple[str, int]] = None,
    ) -> None:
        if line_idx in lineas_inactivas:
            return
        clave = (line_idx, rule_idx)
        if clave not in candidatos or start_b < candidatos[clave][0]:
            candidatos[clave] = (start_b, end_b, familia, nuevo, funcion_ecr)

    # Recorrido en pre-orden con pila explícita para respetar el orden de asignaciones
    pila: List[Tuple[Any, bool]] = [(tree.root_node, False)]
    while pila:
        node, en_main = pila.pop()
        ntype = node.type  # type: ignore[attr-defined]
        line_idx = node.start_point.row  # type: ignore[attr-defined]

        if ntype == "function_definition":
            asignaciones_por_fn = {}
            en_main = _nombre_funcion_def(node) == "main"

        if ntype in ("string_literal", "char_literal", "comment"):
            continue

        if ntype == "init_declarator":
            decl = node.child_by_field_name("declarator")  # type: ignore[attr-defined]
            val = node.child_by_field_name("value")  # type: ignore[attr-defined]
            fn_falla = _extraer_llamada_falla(val)
            if decl is not None and fn_falla:
                # Obtener identificador del declarador (ej. `*v` -> `v`)
                d = decl
                while d is not None and d.type != "identifier":
                    d = d.child_by_field_name("declarator") or next(
                        (c for c in d.children if c.is_named), None
                    )
                if d is not None and d.type == "identifier":
                    var_name = (d.text or b"").decode("utf-8", errors="replace")
                    asignaciones_por_fn[var_name] = (fn_falla, line_idx + 1)

        elif ntype == "assignment_expression":
            left = node.child_by_field_name("left")  # type: ignore[attr-defined]
            right = node.child_by_field_name("right")  # type: ignore[attr-defined]
            fn_falla = _extraer_llamada_falla(right)
            if left is not None and fn_falla:
                var_name = (left.text or b"").decode("utf-8", errors="replace").strip()
                asignaciones_por_fn[var_name] = (fn_falla, line_idx + 1)

        if ntype == "binary_expression":
            left = node.child_by_field_name("left")  # type: ignore[attr-defined]
            op = node.child_by_field_name("operator")  # type: ignore[attr-defined]
            right = node.child_by_field_name("right")  # type: ignore[attr-defined]
            if left is not None and op is not None and right is not None:
                op_txt = (op.text or b"").decode("utf-8", errors="replace")
                if op_txt in _BINARIOS_AST and left.end_point.row == right.start_point.row == line_idx:
                    rule_idx, familia, nuevo = _BINARIOS_AST[op_txt]
                    _registrar(line_idx, rule_idx, left.end_byte, right.start_byte, familia, nuevo)

        elif ntype == "update_expression":
            op = node.child_by_field_name("operator")  # type: ignore[attr-defined]
            if op is None:
                op = next(
                    (c for c in node.children if c.type in ("++", "--")),  # type: ignore[attr-defined]
                    None,
                )
            if op is not None:
                op_txt = (op.text or b"").decode("utf-8", errors="replace")
                if op_txt in _UNARIOS_INC_AST:
                    rule_idx, familia, nuevo = _UNARIOS_INC_AST[op_txt]
                    _registrar(op.start_point.row, rule_idx, op.start_byte, op.end_byte, familia, nuevo)

        elif ntype == "unary_expression":
            op = node.child_by_field_name("operator")  # type: ignore[attr-defined]
            if op is not None and (op.text or b"").decode("utf-8", errors="replace") == "!":
                _registrar(op.start_point.row, 13, op.start_byte, op.end_byte, "LNR", "")

        elif ntype == "return_statement" and not en_main:
            hijos_valor = [
                c for c in node.children  # type: ignore[attr-defined]
                if c.is_named and c.type != "comment"
            ]
            if len(hijos_valor) == 1:
                val = hijos_valor[0]
                if val.type == "number_literal" or (
                    val.type == "unary_expression"
                    and val.child_by_field_name("operator") is not None
                    and (val.child_by_field_name("operator").text or b"").decode() == "-"
                    and val.child_by_field_name("argument") is not None
                    and val.child_by_field_name("argument").type == "number_literal"
                ):
                    orig_ret = source_bytes[node.start_byte:val.end_byte].decode("utf-8", errors="replace")
                    if re.fullmatch(r"return\s+-?\d+", orig_ret) and node.start_point.row == val.end_point.row:
                        _registrar(
                            line_idx,
                            14,
                            node.start_byte,
                            val.end_byte,
                            "RVR",
                            _retorno_constante(orig_ret),
                        )

        elif ntype == "call_expression" and sanitizers:
            fn = node.child_by_field_name("function")  # type: ignore[attr-defined]
            args = node.child_by_field_name("arguments")  # type: ignore[attr-defined]
            if fn is not None and args is not None and fn.type == "identifier":
                fn_name = (fn.text or b"").decode("utf-8", errors="replace")
                inner = source_bytes[args.start_byte + 1:args.end_byte - 1].decode("utf-8", errors="replace")
                if fn_name == "malloc" and inner.strip() and args.start_point.row == args.end_point.row:
                    _registrar(
                        line_idx,
                        15,
                        args.start_byte + 1,
                        args.end_byte - 1,
                        "MSR",
                        f"({inner}) - 1",
                    )
                elif fn_name == "free" and inner.strip() and node.start_point.row == node.end_point.row:
                    _registrar(line_idx, 16, node.start_byte, node.end_byte, "FDR", "(void)0")

        elif ntype == "if_statement" and errores:
            cond = node.child_by_field_name("condition")  # type: ignore[attr-defined]
            if cond is not None and cond.start_point.row == cond.end_point.row:
                inner = source_bytes[cond.start_byte + 1:cond.end_byte - 1].decode("utf-8", errors="replace")
                chequeo = chequeo_de_error(f"if ({inner})")
                if chequeo is not None:
                    fn_ecr: Optional[Tuple[str, int]] = (
                        (chequeo["fn"], line_idx + 1)
                        if chequeo.groupdict().get("fn")
                        else asignaciones_por_fn.get(chequeo["var"])
                    )
                    if fn_ecr is not None:
                        _registrar(
                            line_idx,
                            17,
                            cond.start_byte + 1,
                            cond.end_byte - 1,
                            "ECR",
                            f"({inner}) && 0",
                            funcion_ecr=fn_ecr,
                        )

        # Apilar hijos en orden inverso para recorrer en pre-orden izquierdo-derecho
        for hijo in reversed(node.children):  # type: ignore[attr-defined]
            pila.append((hijo, en_main))

    mutants_with_code: List[Tuple[Mutant, str]] = []
    prioridades: Dict[int, int] = {}
    mutant_id = 1

    for (line_idx, _rule_idx) in sorted(candidatos):
        if mutant_id > tope:
            break
        start_b, end_b, m_type, nuevo, funcion_ecr = candidatos[(line_idx, _rule_idx)]
        line_str = lines[line_idx] if line_idx < len(lines) else ""
        prioridad = prioridad_catedra(m_type, line_str) if perfil == "catedra" else 0
        if prioridad is None:
            continue

        mutated_bytes = source_bytes[:start_b] + nuevo.encode("utf-8") + source_bytes[end_b:]
        mutated_code = mutated_bytes.decode("utf-8", errors="replace")
        mutated_lines = mutated_code.splitlines()
        mutated_line = mutated_lines[line_idx] if line_idx < len(mutated_lines) else ""

        m = Mutant(
            id=mutant_id,
            file_path=str(file_path),
            line_number=line_idx + 1,
            original_snippet=line_str.strip(),
            mutated_snippet=mutated_line.strip(),
            mutation_type=m_type,
            status=MutationStatus.SURVIVED,
            funcion=funcion_ecr[0] if funcion_ecr else None,
            linea_llamada=funcion_ecr[1] if funcion_ecr else None,
        )
        mutants_with_code.append((m, mutated_code))
        prioridades[m.id] = prioridad
        mutant_id += 1

    if perfil == "catedra":
        mutants_with_code.sort(key=lambda par: (prioridades[par[0].id], par[0].id))
        mutants_with_code = mutants_with_code[:MAX_MUTANTES]
        for nuevo_id, (m, _) in enumerate(mutants_with_code, 1):
            m.id = nuevo_id
    return mutants_with_code


def generate_mutants_for_file(file_path: Path, sanitizers: bool = False,
                              errores: bool = False, perfil: str = "completo") -> List[Tuple[Mutant, str]]:
    """Genera lista de mutantes y el código fuente C completo de cada mutante."""
    if perfil not in PERFILES:
        raise ValueError(f"perfil desconocido: {perfil} (usá {' o '.join(PERFILES)})")
    # Con `catedra` se generan todos los candidatos, se ordenan por prioridad y recién ahí se corta.
    tope = MAX_MUTANTES if perfil == "completo" else MAX_MUTANTES * 20
    content = file_path.read_text(encoding="utf-8", errors="replace")

    ast_mutants = _generate_mutants_ast(content, file_path, sanitizers, errores, perfil, tope)
    if ast_mutants is not None:
        return ast_mutants

    prioridades: Dict[int, int] = {}
    mutants_with_code: List[Tuple[Mutant, str]] = []
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
