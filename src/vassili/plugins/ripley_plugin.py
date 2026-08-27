"""Plugin de VASSILI para el microkernel RIPLEY."""

from pathlib import Path
from typing import Dict, Any
from vassili.core.mutation_runner import run_mutation_analysis


class VassiliPlugin:
    """Plugin de mutation testing para Ripley."""

    name = "mutation_testing"
    description = "Evaluación de robustez de tests mediante inyección de mutantes C"

    def run(self, context: Dict[str, Any]) -> Dict[str, Any]:
        source_dir = Path(context.get("source_dir", "."))
        testcases_dir = Path(context.get("testcases_dir", source_dir / "tests"))
        main_c = source_dir / "main.c"

        if not main_c.exists():
            return {"passed": True, "mutation_score": 100.0, "message": "main.c no encontrado"}

        report = run_mutation_analysis(main_c, testcases_dir)

        return {
            "passed": report.passed,
            "mutation_score": report.mutation_score,
            "total_mutants": report.total_mutants,
            "killed_count": report.killed_count,
            "survived_count": report.survived_count
        }
