"""Ejecutor de pruebas sobre mutantes para cálculo de Mutation Score."""

import tempfile
import subprocess
from pathlib import Path
from typing import List
from vassili.core.models import MutationReport, MutationStatus, Mutant
from vassili.core.mutator import generate_mutants_for_file


def run_mutation_analysis(
    source_file: Path,
    testcases_dir: Path,
    timeout: float = 2.0,
    min_score: float = 70.0
) -> MutationReport:
    """Ejecuta todos los mutantes contra los testcases del directorio."""
    mutants_with_code = generate_mutants_for_file(source_file)
    if not mutants_with_code:
        return MutationReport(
            source_file=str(source_file),
            total_mutants=0,
            killed_count=0,
            survived_count=0,
            mutation_score=100.0,
            mutants=[],
            passed=True
        )

    in_files = sorted(testcases_dir.glob("*.in"))
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

            # 1. Compilar mutante
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
    score = (killed / valid_mutants * 100.0) if valid_mutants > 0 else 100.0

    return MutationReport(
        source_file=str(source_file),
        total_mutants=len(evaluated_mutants),
        killed_count=killed,
        survived_count=survived,
        compile_error_count=comp_errors,
        mutation_score=round(score, 2),
        mutants=evaluated_mutants,
        passed=(score >= min_score)
    )
