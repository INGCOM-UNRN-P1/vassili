# VASSILI — Motor de Mutation Testing en C

**VASSILI** evalúa la calidad y exhaustividad real de las suites de prueba de los estudiantes mediante la inyección procedural de mutantes sintéticos en el código fuente C (operadores aritméticos, relacionales y lógicos) y calcula el **Mutation Score** (% de mutantes detectados).

---

## 🎯 Alcance

### Qué cubre
- Motor de Mutation Testing para código fuente C y evaluación de calidad de suites de pruebas.
- Aplicación de operadores de mutación sintáctica sobre el AST (inversión de comparaciones condicionales, mutación de operadores aritméticos, reemplazo de literales y constantes).
- Ejecución de la suite de pruebas contra cada mutante generado.
- Cálculo cuantitativo del Mutation Score (porcentaje de mutantes eliminados respecto al total) y reporte de mutantes supervivientes.

### Qué no cubre (Límites y Delegación)
- Cobertura lógica estructural MC/DC (delegado a `dietrich`).
- Fuzzing de entradas extremas de I/O (delegado a `drake`).
- Orquestación de calificaciones masivas de cursos (delegado a `dredd`).

---

## 📋 Requisitos

### Requisitos de Sistema y Entorno
- Linux / POSIX o Windows (MSYS2 / WSL). Python >= 3.10.

### Dependencias Externas y Binarios
- `gcc`.

### Integración en el Ecosistema
- CLI `vassili`. Plugin registrado en `ripley.plugins` (`mutation_testing`).

---

## 🚀 Uso Rápido

```bash
# Ejecutar análisis de mutación sobre un archivo C con testcases
vassili mutate solucion_alumno.c --tests-dir tests/

# Exigir un Mutation Score mínimo del 80%
vassili mutate solucion_alumno.c --tests-dir tests/ --min-score 80

# Salida estructurada JSON
vassili mutate solucion_alumno.c --tests-dir tests/ --json
```

---

## 🔬 Operadores de Mutación

- **`AOR`** (Arithmetic Operator Replacement): `+` ➔ `-`, `*` ➔ `/`.
- **`ROR`** (Relational Operator Replacement): `==` ➔ `!=`, `<` ➔ `<=`, `>` ➔ `>=`.
- **`LCR`** (Logical Connector Replacement): `&&` ➔ `||`.
