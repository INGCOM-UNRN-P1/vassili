"""Modelos de datos para el motor de mutation testing en VASSILI."""

from enum import Enum
from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class MutationStatus(str, Enum):
    KILLED = "killed"
    SURVIVED = "survived"
    COMPILE_ERROR = "compile_error"
    TIMEOUT = "timeout"
    # El compilador genera exactamente el mismo código que para el original: ningún test puede
    # matarlo, así que no entra en el score (QoL #1008).
    EQUIVALENT = "equivalent"


class Mutant(BaseModel):
    id: int
    file_path: str
    line_number: int
    original_snippet: str
    mutated_snippet: str
    mutation_type: str  # ROR, AOR, UOI, LCR, LNR, RVR, MSR, FDR (ver el README)
    status: MutationStatus = MutationStatus.SURVIVED
    killing_test: Optional[str] = None
    # Con una suite de p1_test: la aserción que lo mató («prueba.c:42: ASSERT_INT_EQ(…)») o la señal.
    asercion: Optional[str] = None
    # Para un mutante que sobrevivió: qué caso de prueba falta para matarlo (QoL #1009).
    sugerencia: Optional[str] = None


class ResumenOperador(BaseModel):
    """Lo que la suite hizo con los mutantes de una familia (ROR, AOR…)."""
    generados: int = 0
    asesinados: int = 0  # incluye los que terminaron por timeout
    sobrevivientes: int = 0
    equivalentes: int = 0
    no_compilan: int = 0
    score: Optional[float] = None  # asesinados / (asesinados + sobrevivientes); None sin mutantes válidos


class MutationReport(BaseModel):
    schema_version: str = "1.1.0"
    source_file: str
    suite: Optional[str] = None  # la suite de p1_test, si se usó en lugar de casos .in/.out
    # Por familia de operador: cuáles aniquila la suite y cuáles no (Ola 12).
    por_operador: Dict[str, ResumenOperador] = Field(default_factory=dict)
    total_mutants: int = 0
    killed_count: int = 0
    survived_count: int = 0
    compile_error_count: int = 0
    timeout_count: int = 0  # mutantes asesinados por agotar el tiempo (incluidos en killed_count)
    equivalent_count: int = 0  # mutantes equivalentes (mismo código objeto): fuera del score
    sanitizers: bool = False  # mutantes y suite corridos con AddressSanitizer (detecta fugas y desbordes)
    aislamiento: str = ""  # sandbox de cada corrida: nostromo (bwrap), nostromo sin bwrap o límites propios
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
