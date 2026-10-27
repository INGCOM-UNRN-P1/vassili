"""Ejecutor de pruebas sobre mutantes para cálculo de Mutation Score."""

import math
import os
import re
from contextlib import contextmanager
from dataclasses import dataclass
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable, Dict, Iterator, List, NamedTuple, Optional, Sequence, Tuple

from vassili.core.models import MutationReport, MutationStatus, Mutant, ResumenOperador
from vassili.core.mutator import FAMILIAS_DE_ERRORES, generate_mutants_for_file

# Con --sanitizers, mutantes y suite corren con AddressSanitizer: es lo único que detecta una
# reserva de menos (MSR) o un free que falta (FDR). La fuga sale con código 23.
FLAGS_SANITIZERS = ["-fsanitize=address", "-fno-omit-frame-pointer", "-g"]
_ENTORNO_SANITIZERS = {"ASAN_OPTIONS": "detect_leaks=1:exitcode=23"}

# Cada corrida está aislada en su proceso con límites (QoL #1011): un mutante con un bucle
# infinito se corta por tiempo, uno que reserva sin parar por memoria y uno que imprime sin
# parar por tamaño de salida (va a un archivo, no a la memoria de vassili). Con nostromo (extra
# `ecosistema`) corre además dentro de su sandbox (bwrap): sin red y sin escribir fuera de él,
# así que un mutante que borra o pisa archivos no toca la máquina del evaluador (Ola 12).
LIMITE_MEMORIA_MB = 512
LIMITE_SALIDA_BYTES = 8 * 1024 * 1024

AISLAMIENTO_PROPIO = "propio (límites POSIX)"


class Ejecucion(NamedTuple):
    retorno: int
    stdout: str
    stderr: str
    aislamiento: str


@dataclass(frozen=True)
class SuiteP1:
    """Una suite de p1_test (`prueba.c` con su main) que se compila junto al módulo mutado.

    En lugar de comparar la salida con `.out`, cada mutante se enlaza con la suite y se corre con
    `-q -f`: p1_test deja en stderr la línea `P1_FALLO` de la aserción que lo mató (treadstone
    41b344d) y se detiene en el primer test que falla (Ola 12, QoL #1269).
    """
    prueba: Path
    incluir: Tuple[Path, ...] = ()
    enlazar: Tuple[Path, ...] = ()


ARGS_SUITE = ("-q", "-f")
_RE_LINEA_P1 = re.compile(r"^P1_(FALLO|CRASH)\t([^\t]*)\t([^\t\r\n]*)(?:\t([^\r\n]*))?$", re.M)


def _biblioteca_p1_test(desde: Path) -> Optional[Path]:
    """`libs/p1_test` de la plantilla de TP, buscándolo hacia arriba desde la suite."""
    for carpeta in [desde, *desde.parents][:5]:
        candidata = carpeta / "libs" / "p1_test"
        if (candidata / "p1_test.h").is_file() or (candidata / "include" / "p1_test.h").is_file():
            return candidata
    return None


def resolver_suite(prueba: Path, incluir: Sequence[Path] = (), enlazar: Sequence[Path] = ()) -> SuiteP1:
    """La suite con sus directorios de headers y lo que hay que enlazar.

    Sin `incluir` ni `enlazar` se usa el `libs/p1_test` de la plantilla: sus headers y, para
    enlazar, sus fuentes (`src/*.c`) o la biblioteca ya compilada (`libp1_test.a`)."""
    prueba = Path(prueba).resolve()
    incluir = tuple(Path(d).resolve() for d in incluir)
    enlazar = tuple(Path(f).resolve() for f in enlazar)
    if not incluir and not enlazar:
        lib = _biblioteca_p1_test(prueba.parent)
        if lib is not None:
            incluir = tuple(d for d in (lib / "include", lib) if d.is_dir())
            fuentes = sorted((lib / "src").glob("*.c"))
            archivo = next((a for a in (lib / "libp1_test.a", lib / "build" / "libp1_test.a") if a.is_file()), None)
            enlazar = tuple(fuentes) if fuentes else ((archivo,) if archivo else ())
    return SuiteP1(prueba, incluir, enlazar)


def asercion_de(stderr: str) -> Tuple[Optional[str], Optional[str]]:
    """(test, aserción) de la primera línea P1_FALLO / P1_CRASH de una corrida de p1_test."""
    m = _RE_LINEA_P1.search(stderr)
    if not m:
        return None, None
    tipo, test, ubicacion, expresion = m.groups()
    if tipo == "CRASH":
        return test, ubicacion
    return test, f"{ubicacion}: {expresion}" if expresion else ubicacion


# Qué caso de prueba falta para matar un mutante que sobrevivió (QoL #1009).
SUGERENCIAS: Dict[str, str] = {
    "ROR": "Agregá un caso en el borde de esa comparación: el valor justo igual, uno menos y uno más "
           "(n = 0, n = 1, el último elemento).",
    "AOR": "Agregá un caso donde el resultado dependa de ese cálculo y verificá el valor exacto.",
    "UOI": "Agregá un caso que recorra el lazo más de una vez y verifique cada resultado.",
    "LCR": "Agregá un caso donde solo una de las dos condiciones sea verdadera.",
    "LNR": "Agregá un caso con la condición verdadera y otro con la condición falsa.",
    "RVR": "Verificá el valor que devuelve la función en un caso que llegue a ese return.",
    "MSR": "Agregá un caso que use toda la memoria reservada: con --sanitizers el desborde se detecta.",
    "FDR": "Agregá un caso que pase por esa liberación: con --sanitizers la fuga se detecta.",
    "ECR": "Ningún caso hace fallar esa llamada: el camino de error no está probado. Probalo con el "
           "plan de vasquez (--plan-vasquez) o con P1_FALLAR_EN en la suite de p1_test.",
}


def _compilar_con_daedalus(fuentes: List[Path], m_bin: Path, flags: List[str]) -> Optional[bool]:
    try:
        from daedalus.core.compiler import compilar_archivos
    except ImportError:
        return None  # sin el extra `ecosistema` se usa el camino propio
    res = compilar_archivos(fuentes, binario_salida=m_bin, flags_adicionales=flags)
    return res.exito


def _flags_de_headers(original: Path, suite: Optional[SuiteP1]) -> List[str]:
    """El mutante se escribe en un temporal: sus `#include "modulo.h"` se buscan junto al original."""
    return [f"-I{original.resolve().parent}", *(f"-I{d}" for d in (suite.incluir if suite else ()))]


def _compilar(fuente: Path, binario: Path, sanitizers: bool = False, suite: Optional[SuiteP1] = None,
              original: Optional[Path] = None) -> bool:
    """Compila delegando en daedalus, con gcc como respaldo; con una suite, enlazada a ella."""
    flags = ["-O0"] + (FLAGS_SANITIZERS if sanitizers else []) + _flags_de_headers(original or fuente, suite)
    fuentes = [fuente, *([suite.prueba, *suite.enlazar] if suite else [])]
    daed_ok = _compilar_con_daedalus(fuentes, binario, flags)
    if daed_ok is not None:
        return daed_ok
    comp = subprocess.run(
        ["gcc", *flags, *map(str, fuentes), "-o", str(binario), "-lm"],
        capture_output=True,
        check=False,
    )
    return comp.returncode == 0


def _limites(timeout: float, sanitizers: bool) -> Optional[Callable[[], None]]:
    if os.name != "posix":
        return None
    import resource

    def aplicar() -> None:
        cpu = math.ceil(timeout) + 1
        resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
        resource.setrlimit(resource.RLIMIT_FSIZE, (LIMITE_SALIDA_BYTES, LIMITE_SALIDA_BYTES))
        if not sanitizers:  # ASan reserva muchísimo espacio virtual: con límite no arranca
            memoria = LIMITE_MEMORIA_MB * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (memoria, memoria))

    return aplicar


@contextmanager
def _entorno_sanitizers(sanitizers: bool) -> Iterator[None]:
    """nostromo no recibe un entorno: hereda el de vassili, que se ajusta mientras dura la corrida."""
    if not sanitizers:
        yield
        return
    previo = {k: os.environ.get(k) for k in _ENTORNO_SANITIZERS}
    os.environ.update(_ENTORNO_SANITIZERS)
    try:
        yield
    finally:
        for clave, valor in previo.items():
            if valor is None:
                os.environ.pop(clave, None)
            else:
                os.environ[clave] = valor


def _ejecutar_en_nostromo(binario: Path, args: Sequence[str], entrada: str, timeout: float,
                          sanitizers: bool) -> Optional[Ejecucion]:
    try:
        from nostromo.core.sandbox import ejecutar_aislado
    except ImportError:
        return None  # sin el extra `ecosistema` se usa el camino propio
    with _entorno_sanitizers(sanitizers):
        res = ejecutar_aislado(binario, args=list(args), stdin_texto=entrada, timeout_segundos=timeout,
                               memoria_mb=LIMITE_MEMORIA_MB, archivo_mb=LIMITE_SALIDA_BYTES // (1024 * 1024))
    if res.error_tipo == "TIMEOUT":
        raise subprocess.TimeoutExpired([str(binario), *args], timeout)
    aislamiento = "nostromo (bwrap)" if res.aislado else "nostromo (sólo límites, sin bwrap)"
    return Ejecucion(res.codigo_retorno, res.stdout[:LIMITE_SALIDA_BYTES], res.stderr[:LIMITE_SALIDA_BYTES],
                     aislamiento)


def aislamiento_disponible() -> str:
    """Con qué aislamiento van a correr los mutantes en esta máquina (va en el reporte)."""
    try:
        from nostromo.core.sandbox import bwrap_funciona
    except ImportError:
        return AISLAMIENTO_PROPIO
    bwrap = shutil.which("bwrap")
    if os.name == "posix" and bwrap and bwrap_funciona(bwrap):
        return "nostromo (bwrap)"
    return "nostromo (sólo límites, sin bwrap)"


def _ejecutar(binario: Path, entrada: str, timeout: float, sanitizers: bool,
              args: Sequence[str] = ()) -> Ejecucion:
    """Corre el binario aislado; `subprocess.TimeoutExpired` si no termina a tiempo."""
    en_sandbox = _ejecutar_en_nostromo(binario, args, entrada, timeout, sanitizers)
    if en_sandbox is not None:
        return en_sandbox
    entorno = {**os.environ, **_ENTORNO_SANITIZERS} if sanitizers else None
    with tempfile.TemporaryFile() as salida, tempfile.TemporaryFile() as errores:
        proc = subprocess.run(
            [str(binario), *args],
            input=entrada.encode("utf-8"),
            stdout=salida,
            stderr=errores,
            timeout=timeout,
            check=False,
            preexec_fn=_limites(timeout, sanitizers),  # noqa: PLW1509 — solo setrlimit, sin hilos
            env=entorno,
        )
        salida.seek(0)
        errores.seek(0)
        return Ejecucion(proc.returncode,
                         salida.read(LIMITE_SALIDA_BYTES).decode("utf-8", errors="replace"),
                         errores.read(LIMITE_SALIDA_BYTES).decode("utf-8", errors="replace"),
                         AISLAMIENTO_PROPIO)


def _falla(binario: Path, in_f: Path, timeout: float, sanitizers: bool) -> bool:
    out_f = in_f.with_suffix(".out")
    esperado = out_f.read_text(encoding="utf-8") if out_f.exists() else None
    corrida = _ejecutar(binario, in_f.read_text(encoding="utf-8"), timeout, sanitizers)
    return corrida.retorno != 0 or (esperado is not None and corrida.stdout.strip() != esperado.strip())


def _casos_que_fallan(binario: Path, in_files: List[Path], timeout: float, sanitizers: bool = False) -> List[str]:
    """Devuelve los casos que el binario no supera."""
    fallidos: List[str] = []
    for in_f in in_files:
        try:
            if _falla(binario, in_f, timeout, sanitizers):
                fallidos.append(in_f.name)
        except subprocess.TimeoutExpired:
            fallidos.append(f"{in_f.name} (timeout)")
    return fallidos


def _fallos_de_la_suite(binario: Path, timeout: float, sanitizers: bool) -> List[str]:
    """Las aserciones que fallan sobre el original (sin -f, para listarlas todas)."""
    try:
        corrida = _ejecutar(binario, "", timeout, sanitizers, args=["-q"])
    except subprocess.TimeoutExpired:
        return ["la suite (timeout)"]
    if corrida.retorno == 0:
        return []
    lineas = [f"{m[1]} ({m[2]}{': ' + m[3] if m[3] else ''})" for m in _RE_LINEA_P1.findall(corrida.stderr)]
    return lineas or [_como_termino(corrida)]


def _como_termino(corrida: Ejecucion) -> str:
    """«la suite (SIGABRT)» si la mató una señal que p1_test no captura (abort de un assert, double
    free…), «la suite (código N)» si salió con un código. Bajo bwrap la señal llega como 128+N."""
    senal = -corrida.retorno if corrida.retorno < 0 else None
    if corrida.aislamiento == "nostromo (bwrap)" and 128 < corrida.retorno < 160:
        senal = corrida.retorno - 128
    if senal is not None:
        import signal

        try:
            return f"la suite ({signal.Signals(senal).name})"
        except ValueError:
            return f"la suite (señal {senal})"
    return f"la suite (código {corrida.retorno})"


class Veredicto(NamedTuple):
    caso: str
    asercion: Optional[str]
    timeout: bool


def _primer_fallo(binario: Path, in_files: List[Path], suite: Optional[SuiteP1], timeout: float,
                  sanitizers: bool) -> Optional[Veredicto]:
    """El caso (y con p1_test, la aserción) que mata al mutante, o None si sobrevive."""
    if suite is not None:
        try:
            corrida = _ejecutar(binario, "", timeout, sanitizers, args=ARGS_SUITE)
        except subprocess.TimeoutExpired:
            return Veredicto("la suite (timeout)", None, True)
        if corrida.retorno == 0:
            return None
        test, asercion = asercion_de(corrida.stderr)
        if asercion:  # el compilador recibe rutas absolutas: se muestra relativa a la suite
            asercion = asercion.replace(f"{suite.prueba.parent}{os.sep}", "")
        return Veredicto(test or _como_termino(corrida), asercion, False)
    for in_f in in_files:
        try:
            # Si crasheó o si la salida no coincide con la esperada -> MUTANTE ASESINADO
            if _falla(binario, in_f, timeout, sanitizers):
                return Veredicto(in_f.name, None, False)
        except subprocess.TimeoutExpired:
            # Un bucle infinito inducido por el mutante lo detecta la suite (cuenta como
            # asesinado en el score) pero se distingue del que muere por salida distinta o crash.
            return Veredicto(f"{in_f.name} (timeout)", None, True)
    return None


def verificar_baseline(
    source_file: Path,
    in_files: List[Path],
    timeout: float,
    sanitizers: bool = False,
    suite: Optional[SuiteP1] = None,
) -> Tuple[bool, List[str]]:
    """Comprueba que la suite apruebe sobre el programa SIN mutar.

    Es la precondición del análisis de mutación: si el original ya falla —por
    ejemplo porque un `.out` tiene la salida equivocada— entonces cualquier
    mutante también diverge, se lo cuenta como asesinado y el score da 100
    sobre una suite que no sirve como oráculo.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        binario = Path(tmp_dir) / "original.bin"
        if not _compilar(source_file, binario, sanitizers, suite):
            if sanitizers:
                return False, ["el programa original no compila con sanitizers (¿falta libasan? corré sin --sanitizers)"]
            if suite is not None:
                return False, [f"el módulo original no compila junto a {suite.prueba.name} (¿falta p1_test? usá -I y --enlazar)"]
            return False, ["el programa original no compila"]
        if suite is not None:
            fallidos = _fallos_de_la_suite(binario, timeout, sanitizers)
        else:
            fallidos = _casos_que_fallan(binario, in_files, timeout, sanitizers)
    return (not fallidos), fallidos


def _codigo_objeto(codigo: str, directorio: Path, flags: Sequence[str] = ()) -> Optional[bytes]:
    """El `.o` optimizado de un fuente, compilado siempre como `prog.c` para que el nombre del
    archivo (que queda en el objeto) no haga distintos a dos fuentes equivalentes."""
    gcc = shutil.which("gcc")
    if not gcc:
        return None
    directorio.mkdir(parents=True, exist_ok=True)
    (directorio / "prog.c").write_text(codigo, encoding="utf-8")
    comp = subprocess.run([gcc, "-O2", *flags, "-c", "prog.c", "-o", "prog.o"], cwd=directorio,
                          capture_output=True, check=False)
    return (directorio / "prog.o").read_bytes() if comp.returncode == 0 else None


def resumir_por_operador(mutantes: List[Mutant]) -> Dict[str, ResumenOperador]:
    """Cuántos mutantes de cada familia generó, mató y dejó vivos la suite, con su score."""
    resumen: Dict[str, ResumenOperador] = {}
    for m in mutantes:
        r = resumen.setdefault(m.mutation_type, ResumenOperador())
        r.generados += 1
        if m.status in (MutationStatus.KILLED, MutationStatus.TIMEOUT):
            r.asesinados += 1
        elif m.status == MutationStatus.SURVIVED:
            r.sobrevivientes += 1
        elif m.status == MutationStatus.EQUIVALENT:
            r.equivalentes += 1
        else:
            r.no_compilan += 1
    for r in resumen.values():
        validos = r.asesinados + r.sobrevivientes
        r.score = round(r.asesinados / validos * 100.0, 2) if validos else None
    return resumen


def run_mutation_analysis(
    source_file: Path,
    testcases_dir: Path,
    timeout: float = 2.0,
    min_score: float = 70.0,
    sanitizers: bool = False,
    suite: Optional[SuiteP1] = None,
    errores: bool = False,
    perfil: str = "completo",
) -> MutationReport:
    """Ejecuta todos los mutantes contra los testcases del directorio, o contra una suite de p1_test."""
    mutants_with_code = generate_mutants_for_file(source_file, sanitizers=sanitizers, errores=errores, perfil=perfil)
    aislamiento = aislamiento_disponible()
    if not mutants_with_code:
        # Sin operadores que mutar no hay nada que medir: no se inventa un 100.
        return MutationReport(
            source_file=str(source_file),
            total_mutants=0,
            killed_count=0,
            survived_count=0,
            mutation_score=0.0,
            mutants=[],
            passed=True,
            evaluable=False,
            motivo_no_evaluable="El fuente no tiene operadores mutables (relacionales, aritméticos ni lógicos).",
            sanitizers=sanitizers,
            aislamiento=aislamiento,
        )

    in_files = [] if suite is not None else sorted(testcases_dir.glob("*.in"))

    baseline_ok, baseline_fallos = verificar_baseline(source_file, in_files, timeout, sanitizers, suite)
    if not baseline_ok:
        # Sin oráculo válido no se informa score: cualquier número sería
        # mérito de la suite rota, no de su capacidad de detectar mutantes.
        return MutationReport(
            source_file=str(source_file),
            total_mutants=len(mutants_with_code),
            killed_count=0,
            survived_count=0,
            mutation_score=0.0,
            mutants=[],
            passed=False,
            baseline_ok=False,
            baseline_fallos=baseline_fallos,
            sanitizers=sanitizers,
            aislamiento=aislamiento,
        )

    evaluated_mutants: List[Mutant] = []
    killed = 0
    survived = 0
    comp_errors = 0
    timeouts = 0
    equivalentes = 0

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        flags_headers = _flags_de_headers(source_file, suite)
        objeto_original = _codigo_objeto(source_file.read_text(encoding="utf-8", errors="replace"),
                                         tmp_path / "original", flags_headers)

        for mutant, code in mutants_with_code:
            m_src = tmp_path / f"mutant_{mutant.id}.c"
            m_bin = tmp_path / f"mutant_{mutant.id}.bin"
            m_src.write_text(code, encoding="utf-8")

            # 1. Compilar mutante delegando en daedalus
            if not _compilar(m_src, m_bin, sanitizers, suite, original=source_file):
                mutant.status = MutationStatus.COMPILE_ERROR
                comp_errors += 1
                evaluated_mutants.append(mutant)
                continue

            # 2. Equivalencia trivial por compilador (QoL #1008): si el código optimizado es
            # idéntico al del original, ningún test puede distinguirlos.
            if objeto_original is not None and _codigo_objeto(code, tmp_path / f"eq_{mutant.id}",
                                                              flags_headers) == objeto_original:
                mutant.status = MutationStatus.EQUIVALENT
                equivalentes += 1
                evaluated_mutants.append(mutant)
                continue

            # 3. Ejecutar contra los casos o la suite
            veredicto = _primer_fallo(m_bin, in_files, suite, timeout, sanitizers)
            # Los chequeos de error (ECR) se informan en por_operador y en el plan, fuera del score.
            en_score = mutant.mutation_type not in FAMILIAS_DE_ERRORES
            if veredicto is not None:
                mutant.status = MutationStatus.TIMEOUT if veredicto.timeout else MutationStatus.KILLED
                mutant.killing_test = veredicto.caso
                mutant.asercion = veredicto.asercion
                if en_score:
                    timeouts += veredicto.timeout
                    killed += 1
            else:
                mutant.status = MutationStatus.SURVIVED
                mutant.sugerencia = SUGERENCIAS.get(mutant.mutation_type)
                survived += en_score

            evaluated_mutants.append(mutant)

    valid_mutants = killed + survived
    # Con 0 mutantes válidos no hay sobre qué medir: el `100.0` de antes salía de
    # dividir por nada y aprobaba un análisis que no evaluó ni un solo mutante.
    evaluable = valid_mutants > 0
    score = (killed / valid_mutants * 100.0) if evaluable else 0.0

    return MutationReport(
        source_file=str(source_file),
        suite=str(suite.prueba) if suite else None,
        perfil=perfil,
        por_operador=resumir_por_operador(evaluated_mutants),
        total_mutants=len(evaluated_mutants),
        killed_count=killed,
        survived_count=survived,
        compile_error_count=comp_errors,
        timeout_count=timeouts,
        equivalent_count=equivalentes,
        mutation_score=round(score, 2),
        # El perfil de cátedra descarta del listado los equivalentes: quedan sólo contados.
        mutants=[m for m in evaluated_mutants
                 if perfil != "catedra" or m.status != MutationStatus.EQUIVALENT],
        passed=evaluable and (score >= min_score),
        baseline_ok=True,
        evaluable=evaluable,
        motivo_no_evaluable=(
            "" if evaluable
            else "Ninguno de los mutantes generados compiló, así que no hubo sobre qué medir la suite."
        ),
        sanitizers=sanitizers,
        aislamiento=aislamiento,
    )
