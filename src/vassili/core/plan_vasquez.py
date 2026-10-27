"""Plan de fallos para vasquez a partir de los chequeos de error que la suite no prueba (Ola 12).

Un mutante ECR quita el `if (p == NULL)` que sigue a un malloc, realloc, fopen…; si sobrevive,
ningún caso hizo fallar esa llamada. El plan pide a vasquez que la haga fallar: un escenario por
cada invocación de esa función (hasta `max_llamadas`), porque el número de invocación en tiempo de
ejecución no se deduce del fuente. Lo lee `vasquez inject <fuentes> --plan <archivo>`, o sin
`--plan` si se llama `vasquez.scenario.yaml` y está junto al primer fuente.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional

from vassili.core.masking import enmascarar_comentarios_y_literales
from vassili.core.models import Mutant, MutationReport, MutationStatus
from vassili.core.mutator import FUNCIONES_QUE_FALLAN

NOMBRE_POR_DEFECTO = "vasquez.scenario.yaml"
# Las causas de fallo que un programa de P1 debería distinguir (las mismas que `vasquez plan`).
ERRNOS = {"fopen": ("ENOENT", "EACCES")}


def chequeos_sin_probar(report: MutationReport) -> List[Mutant]:
    return [m for m in report.mutants
            if m.mutation_type == "ECR" and m.status == MutationStatus.SURVIVED and m.funcion]


def _llamadas_en_el_fuente(fuente: Path, funcion: str) -> int:
    import re

    texto = enmascarar_comentarios_y_literales(fuente.read_text(encoding="utf-8", errors="replace"))
    return len(re.findall(rf"(?<![\w.>]){funcion}\s*\(", texto))


def generar_plan(report: MutationReport, fuente: Path, max_llamadas: int = 10) -> Optional[Dict[str, Any]]:
    """Los escenarios de fallo de las funciones con chequeos sin probar (None si no hay ninguno)."""
    funciones = {m.funcion for m in chequeos_sin_probar(report)}
    escenarios: List[Dict[str, Any]] = []
    for funcion in FUNCIONES_QUE_FALLAN:
        if funcion not in funciones:
            continue
        for llamada in range(1, min(max(_llamadas_en_el_fuente(fuente, funcion), 1), max_llamadas) + 1):
            for nombre_errno in ERRNOS.get(funcion, (None,)):
                escenario: Dict[str, Any] = {"tipo": funcion, "llamada": llamada}
                if nombre_errno:
                    escenario["errno"] = nombre_errno
                escenarios.append(escenario)
    return {"escenarios": escenarios, "opciones": {"fugas": True}} if escenarios else None


def texto_del_plan(plan: Dict[str, Any], report: MutationReport, fuente: Path) -> str:
    """El YAML del plan (el formato de `vasquez.core.plan`), con un encabezado que dice de dónde sale."""
    lineas = [f"# Plan de fallos generado por vassili para {fuente.name}: estos chequeos de error",
              "# sobrevivieron a la suite (ningún caso hizo fallar la llamada):"]
    for m in chequeos_sin_probar(report):
        lineas.append(f"#   línea {m.line_number}: {m.original_snippet}  ({m.funcion}, línea {m.linea_llamada})")
    lineas += [f"# Uso: vasquez inject <main.c y módulos> --plan {NOMBRE_POR_DEFECTO}", "escenarios:"]
    for escenario in plan["escenarios"]:
        claves = list(escenario.items())
        lineas.append(f"  - {claves[0][0]}: {claves[0][1]}")
        lineas.extend(f"    {clave}: {valor}" for clave, valor in claves[1:])
    lineas.append("opciones:")
    lineas.extend(f"  {clave}: {'true' if valor is True else 'false' if valor is False else valor}"
                  for clave, valor in plan["opciones"].items())
    return "\n".join(lineas) + "\n"


def escribir_plan(report: MutationReport, fuente: Path, destino: Path) -> bool:
    """Escribe el plan en `destino` (un directorio recibe `vasquez.scenario.yaml`); False si no hay nada que probar."""
    plan = generar_plan(report, fuente)
    if plan is None:
        return False
    if destino.is_dir():
        destino = destino / NOMBRE_POR_DEFECTO
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(texto_del_plan(plan, report, fuente), encoding="utf-8")
    report.plan_vasquez = str(destino)
    return True
