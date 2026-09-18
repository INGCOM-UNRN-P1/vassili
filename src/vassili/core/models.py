"""Modelos de datos para el motor de mutation testing en VASSILI."""

from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


class MutationStatus(str, Enum):
    KILLED = "killed"
    SURVIVED = "survived"
    COMPILE_ERROR = "compile_error"
    TIMEOUT = "timeout"


class Mutant(BaseModel):
    id: int
    file_path: str
    line_number: int
    original_snippet: str
    mutated_snippet: str
    mutation_type: str  # "AOR" (Arithmetic), "ROR" (Relational), "LCR" (Logical), "RVR" (Return)
    status: MutationStatus = MutationStatus.SURVIVED
    killing_test: Optional[str] = None


class MutationReport(BaseModel):
    schema_version: str = "1.0.0"
    source_file: str
    total_mutants: int = 0
    killed_count: int = 0
    survived_count: int = 0
    compile_error_count: int = 0
    mutation_score: float = 0.0  # (killed / (total - compile_error)) * 100
    mutants: List[Mutant] = Field(default_factory=list)
    passed: bool = True
    # El mutation score solo significa algo si la suite aprueba sobre el
    # programa original: si ya falla ahí, todo mutante "diverge" y el score
    # sale 100 premiando justamente a la suite rota.
    baseline_ok: bool = True
    baseline_fallos: List[str] = Field(default_factory=list)
    # `False` cuando no hubo ni un solo mutante válido sobre el cual medir: el
    # score no significa nada y no debe presentarse como perfección.
    evaluable: bool = True
    motivo_no_evaluable: str = ""
