"""Ejecutor de pruebas sobre mutantes para cálculo de Mutation Score."""

import tempfile
import subprocess
from pathlib import Path
from typing import List, Optional, Tuple
from vassili.core.models import MutationReport, MutationStatus, Mutant
from vassili.core.mutator import generate_mutants_for_file


def _compilar_con_daedalus(m_src: Path, m_bin: Path) -> Optional[bool]:
    try:
        from daedalus.core.compiler import compilar_archivos
        res = compilar_archivos([m_src], binario_salida=m_bin, flags_adicionales=["-O0"])
        return res.exito
    except ImportError:
        import sys
        sibling = Path(__file__).resolve().parents[4] / "daedalus" / "src"
        if sibling.is_dir() and str(sibling) not in sys.path:
            sys.path.insert(0, str(sibling))
            try:
                from daedalus.core.compiler import compilar_archivos
                res = compilar_archivos([m_src], binario_salida=m_bin, flags_adicionales=["-O0"])
                return res.exito
            except ImportError:
                return None
        return None


def _compilar(fuente: Path, binario: Path) -> bool:
    """Compila delegando en daedalus, con gcc como respaldo."""
    daed_ok = _compilar_con_daedalus(fuente, binario)
    if daed_ok is not None:
        return daed_ok
    comp = subprocess.run(
        ["gcc", "-O0", str(fuente), "-o", str(binario)],
        capture_output=True,
        check=False,
    )
    return comp.returncode == 0


def _casos_que_fallan(binario: Path, in_files: List[Path], timeout: float) -> List[str]:
    """Devuelve los casos que el binario no supera."""
    fallidos: List[str] = []
    for in_f in in_files:
        out_f = in_f.with_suffix(".out")
        esperado = out_f.read_text(encoding="utf-8") if out_f.exists() else None
        try:
            res = subprocess.run(
                [str(binario)],
                input=in_f.read_text(encoding="utf-8"),
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            fallidos.append(f"{in_f.name} (timeout)")
            continue
        if res.returncode != 0 or (esperado is not None and res.stdout.strip() != esperado.strip()):
            fallidos.append(in_f.name)
    return fallidos


def verificar_baseline(
    source_file: Path,
    in_files: List[Path],
    timeout: float,
) -> Tuple[bool, List[str]]:
    """Comprueba que la suite apruebe sobre el programa SIN mutar.

    Es la precondición del análisis de mutación: si el original ya falla —por
    ejemplo porque un `.out` tiene la salida equivocada— entonces cualquier
    mutante también diverge, se lo cuenta como asesinado y el score da 100
    sobre una suite que no sirve como oráculo.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        binario = Path(tmp_dir) / "original.bin"
        if not _compilar(source_file, binario):
            return False, ["el programa original no compila"]
        fallidos = _casos_que_fallan(binario, in_files, timeout)
    return (not fallidos), fallidos


def run_mutation_analysis(
    source_file: Path,
    testcases_dir: Path,
    timeout: float = 2.0,
    min_score: float = 70.0
) -> MutationReport:
    """Ejecuta todos los mutantes contra los testcases del directorio."""
    mutants_with_code = generate_mutants_for_file(source_file)
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
        )

    in_files = sorted(testcases_dir.glob("*.in"))

    baseline_ok, baseline_fallos = verificar_baseline(source_file, in_files, timeout)
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
        )

    evaluated_mutants: List[Mutant] = []
    killed = 0
    survived = 0
    comp_errors = 0

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)

        for mutant, code in mutants_with_code:
            m_src = tmp_path / f"mutant_{mutant.id}.c"
            m_bin = tmp_path / f"mutant_{mutant.id}.bin"
            m_src.write_text(code, encoding="utf-8")

            # 1. Compilar mutante delegando en daedalus
            daed_ok = _compilar_con_daedalus(m_src, m_bin)
            if daed_ok is not None:
                if not daed_ok:
                    mutant.status = MutationStatus.COMPILE_ERROR
                    comp_errors += 1
                    evaluated_mutants.append(mutant)
                    continue
            else:
                comp = subprocess.run(
                    ["gcc", "-O0", str(m_src), "-o", str(m_bin)],
                    capture_output=True,
                    check=False
                )
                if comp.returncode != 0:
                    mutant.status = MutationStatus.COMPILE_ERROR
                    comp_errors += 1
                    evaluated_mutants.append(mutant)
                    continue

            # 2. Ejecutar contra testcases
            is_killed = False
            for in_f in in_files:
                out_f = in_f.with_suffix(".out")
                expected_out = out_f.read_text(encoding="utf-8") if out_f.exists() else None
                input_data = in_f.read_text(encoding="utf-8")

                try:
                    res = subprocess.run(
                        [str(m_bin)],
                        input=input_data,
                        capture_output=True,
                        text=True,
                        timeout=timeout,
                        check=False
                    )
                    # Si crasheó o si la salida no coincide con la esperada -> MUTANTE ASESINADO
                    if res.returncode != 0 or (expected_out is not None and res.stdout.strip() != expected_out.strip()):
                        mutant.status = MutationStatus.KILLED
                        mutant.killing_test = in_f.name
                        is_killed = True
                        break
                except subprocess.TimeoutExpired:
                    mutant.status = MutationStatus.KILLED
                    mutant.killing_test = f"{in_f.name} (timeout)"
                    is_killed = True
                    break

            if is_killed:
                killed += 1
            else:
                mutant.status = MutationStatus.SURVIVED
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
        mutation_score=round(score, 2),
        mutants=evaluated_mutants,
        passed=evaluable and (score >= min_score),
        baseline_ok=True,
        evaluable=evaluable,
        motivo_no_evaluable=(
            "" if evaluable
            else "Ninguno de los mutantes generados compiló, así que no hubo sobre qué medir la suite."
        ),
    )
