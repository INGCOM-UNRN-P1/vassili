# VASSILI — Motor de Mutation Testing en C

**VASSILI** evalúa la calidad y exhaustividad real de las suites de prueba de los estudiantes mediante la inyección procedural de mutantes sintéticos en el código fuente C (operadores aritméticos, relacionales y lógicos) y calcula el **Mutation Score** (% de mutantes detectados).

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
