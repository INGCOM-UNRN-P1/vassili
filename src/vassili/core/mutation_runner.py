"""Ejecutor de pruebas sobre mutantes para cálculo de Mutation Score."""

import math
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from vassili.core.models import MutationReport, MutationStatus, Mutant
from vassili.core.mutator import generate_mutants_for_file

# Con --sanitizers, mutantes y suite corren con AddressSanitizer: es lo único que detecta una
# reserva de menos (MSR) o un free que falta (FDR). La fuga sale con código 23.
FLAGS_SANITIZERS = ["-fsanitize=address", "-fno-omit-frame-pointer", "-g"]
_ENTORNO_SANITIZERS = {"ASAN_OPTIONS": "detect_leaks=1:exitcode=23"}

# Cada corrida está aislada en su proceso con límites (QoL #1011): un mutante con un bucle
# infinito se corta por tiempo, uno que reserva sin parar por memoria y uno que imprime sin
# parar por tamaño de salida (va a un archivo, no a la memoria de vassili).
LIMITE_MEMORIA_MB = 512
LIMITE_SALIDA_BYTES = 8 * 1024 * 1024

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
}


def _compilar_con_daedalus(m_src: Path, m_bin: Path, flags: List[str]) -> Optional[bool]:
    try:
        from daedalus.core.compiler import compilar_archivos
    except ImportError:
        return None  # sin el extra `ecosistema` se usa el camino propio
    res = compilar_archivos([m_src], binario_salida=m_bin, flags_adicionales=flags)
    return res.exito


def _compilar(fuente: Path, binario: Path, sanitizers: bool = False) -> bool:
    """Compila delegando en daedalus, con gcc como respaldo."""
    flags = ["-O0"] + (FLAGS_SANITIZERS if sanitizers else [])
    daed_ok = _compilar_con_daedalus(fuente, binario, flags)
    if daed_ok is not None:
        return daed_ok
    comp = subprocess.run(
        ["gcc", *flags, str(fuente), "-o", str(binario)],
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


def _ejecutar(binario: Path, entrada: str, timeout: float, sanitizers: bool) -> Tuple[int, str]:
    """Corre el binario aislado; `subprocess.TimeoutExpired` si no termina a tiempo."""
    entorno = {**os.environ, **_ENTORNO_SANITIZERS} if sanitizers else None
    with tempfile.TemporaryFile() as salida:
        proc = subprocess.run(
            [str(binario)],
            input=entrada.encode("utf-8"),
            stdout=salida,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
            check=False,
            preexec_fn=_limites(timeout, sanitizers),  # noqa: PLW1509 — solo setrlimit, sin hilos
            env=entorno,
        )
        salida.seek(0)
        return proc.returncode, salida.read(LIMITE_SALIDA_BYTES).decode("utf-8", errors="replace")


def _falla(binario: Path, in_f: Path, timeout: float, sanitizers: bool) -> bool:
    out_f = in_f.with_suffix(".out")
    esperado = out_f.read_text(encoding="utf-8") if out_f.exists() else None
    ret, stdout = _ejecutar(binario, in_f.read_text(encoding="utf-8"), timeout, sanitizers)
    return ret != 0 or (esperado is not None and stdout.strip() != esperado.strip())


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


def verificar_baseline(
    source_file: Path,
    in_files: List[Path],
    timeout: float,
    sanitizers: bool = False,
) -> Tuple[bool, List[str]]:
    """Comprueba que la suite apruebe sobre el programa SIN mutar.

    Es la precondición del análisis de mutación: si el original ya falla —por
    ejemplo porque un `.out` tiene la salida equivocada— entonces cualquier
    mutante también diverge, se lo cuenta como asesinado y el score da 100
    sobre una suite que no sirve como oráculo.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        binario = Path(tmp_dir) / "original.bin"
        if not _compilar(source_file, binario, sanitizers):
            if sanitizers:
                return False, ["el programa original no compila con sanitizers (¿falta libasan? corré sin --sanitizers)"]
            return False, ["el programa original no compila"]
        fallidos = _casos_que_fallan(binario, in_files, timeout, sanitizers)
    return (not fallidos), fallidos


def _codigo_objeto(codigo: str, directorio: Path) -> Optional[bytes]:
    """El `.o` optimizado de un fuente, compilado siempre como `prog.c` para que el nombre del
    archivo (que queda en el objeto) no haga distintos a dos fuentes equivalentes."""
    gcc = shutil.which("gcc")
    if not gcc:
        return None
    directorio.mkdir(parents=True, exist_ok=True)
    (directorio / "prog.c").write_text(codigo, encoding="utf-8")
    comp = subprocess.run([gcc, "-O2", "-c", "prog.c", "-o", "prog.o"], cwd=directorio,
                          capture_output=True, check=False)
    return (directorio / "prog.o").read_bytes() if comp.returncode == 0 else None


def run_mutation_analysis(
    source_file: Path,
    testcases_dir: Path,
    timeout: float = 2.0,
    min_score: float = 70.0,
    sanitizers: bool = False,
) -> MutationReport:
    """Ejecuta todos los mutantes contra los testcases del directorio."""
    mutants_with_code = generate_mutants_for_file(source_file, sanitizers=sanitizers)
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
        )

    in_files = sorted(testcases_dir.glob("*.in"))

    baseline_ok, baseline_fallos = verificar_baseline(source_file, in_files, timeout, sanitizers)
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
        )

    evaluated_mutants: List[Mutant] = []
    killed = 0
    survived = 0
    comp_errors = 0
    timeouts = 0
    equivalentes = 0

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        objeto_original = _codigo_objeto(source_file.read_text(encoding="utf-8", errors="replace"),
                                         tmp_path / "original")

        for mutant, code in mutants_with_code:
            m_src = tmp_path / f"mutant_{mutant.id}.c"
            m_bin = tmp_path / f"mutant_{mutant.id}.bin"
            m_src.write_text(code, encoding="utf-8")

            # 1. Compilar mutante delegando en daedalus
            if not _compilar(m_src, m_bin, sanitizers):
                mutant.status = MutationStatus.COMPILE_ERROR
                comp_errors += 1
                evaluated_mutants.append(mutant)
                continue

            # 2. Equivalencia trivial por compilador (QoL #1008): si el código optimizado es
            # idéntico al del original, ningún test puede distinguirlos.
            if objeto_original is not None and _codigo_objeto(code, tmp_path / f"eq_{mutant.id}") == objeto_original:
                mutant.status = MutationStatus.EQUIVALENT
                equivalentes += 1
                evaluated_mutants.append(mutant)
                continue

            # 3. Ejecutar contra testcases
            is_killed = False
            for in_f in in_files:
                try:
                    # Si crasheó o si la salida no coincide con la esperada -> MUTANTE ASESINADO
                    if _falla(m_bin, in_f, timeout, sanitizers):
                        mutant.status = MutationStatus.KILLED
                        mutant.killing_test = in_f.name
                        is_killed = True
                        break
                except subprocess.TimeoutExpired:
                    # Un bucle infinito inducido por el mutante lo detecta la suite
                    # (cuenta como asesinado en el score) pero se distingue del que
                    # muere por salida distinta o crash.
                    mutant.status = MutationStatus.TIMEOUT
                    mutant.killing_test = f"{in_f.name} (timeout)"
                    timeouts += 1
                    is_killed = True
                    break

            if is_killed:
                killed += 1
            else:
                mutant.status = MutationStatus.SURVIVED
                mutant.sugerencia = SUGERENCIAS.get(mutant.mutation_type)
                survived += 1

            evaluated_mutants.append(mutant)

    valid_mutants = killed + survived
    # Con 0 mutantes válidos no hay sobre qué medir: el `100.0` de antes salía de
    # dividir por nada y aprobaba un análisis que no evaluó ni un solo mutante.
    evaluable = valid_mutants > 0
    score = (killed / valid_mutants * 100.0) if evaluable else 0.0

    return MutationReport(
        source_file=str(source_file),
        total_mutants=len(evaluated_mutants),
        killed_count=killed,
        survived_count=survived,
        compile_error_count=comp_errors,
        timeout_count=timeouts,
        equivalent_count=equivalentes,
        mutation_score=round(score, 2),
        mutants=evaluated_mutants,
        passed=evaluable and (score >= min_score),
        baseline_ok=True,
        evaluable=evaluable,
        motivo_no_evaluable=(
            "" if evaluable
            else "Ninguno de los mutantes generados compiló, así que no hubo sobre qué medir la suite."
        ),
        sanitizers=sanitizers,
    )
