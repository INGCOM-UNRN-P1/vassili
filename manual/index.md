---
title: "Manual de Referencia: vassili"
subtitle: "Vassili — Motor de Mutation Testing en C para Evaluación de Calidad de Suites de Pruebas"
author: "Cátedra de Algoritmos y Programación"
date: "2026-08-31"
---

(manual-vassili)=
# Vassili — Motor de Mutation Testing en C para Evaluación de Calidad de Suites de Pruebas

````{abstract}
**Rol en el ecosistema:** Evaluación de la efectividad de los tests unitarios mediante la inyección de mutaciones deliberadas en el código fuente (cambio de operadores `+` por `-`, `<` por `<=`, constantes) para verificar si los tests fallan.
````

---

(manual-vassili-proposito)=
## 1. Propósito y Filosofía Pedagógica

La herramienta **`vassili`** forma parte del ecosistema oficial de software de la cátedra. Su diseño sigue principios pedagógicos rigurosos:

1. **Evidencia Técnica Directa**: Todo diagnóstico se fundamenta en la norma ISO C (C11/C23), en el modelo de memoria del sistema o en convenciones arquitectónicas formales.
2. **Acción Correctiva Concreta**: Cada advertencia incluye la prescripción técnica inmediata para resolver el defecto sin recurrir a conjeturas.
3. **Autonomía del Estudiante**: Facilita la autoevaluación local antes de la entrega final del trabajo práctico.
4. **Objetividad Docente**: Estandariza la corrección automática eliminando discrepancias subjetivas en la evaluación.

---

(manual-vassili-instalacion)=
## 2. Instalación y Diagnóstico del Entorno

````{important}
Asegurate de contar con el compilador GCC/Clang y las librerías del sistema instaladas antes de ejecutar `vassili`.
````

Para comprobar el estado de salud de tu entorno de trabajo y las dependencias auxiliares:

````{code-block} bash
# Comprobación de dependencias del sistema
vassili doctor
````

Si se detecta la falta de alguna utilidad (como `gdb`, `valgrind`, `clang-format` o `typst`), el comando indicará el paquete exacto a instalar según tu distribución GNU/Linux o entorno MSYS2.

---

(manual-vassili-comandos)=
## 3. Referencia Completa de Comandos CLI

A continuación se detallan los subcomandos principales disponibles en `vassili`:

| Sintaxis del Comando | Descripción y Efecto |
| :--- | :--- |
| `vassili mutate src/calculadora.c --tests ./bin/test_suite` | Aplica operadores de mutación y calcula el Mutation Score. |
| `vassili report --format html -o reporte_mutaciones.html` | Exporta el informe visual de mutantes vivos y muertos. |
| `vassili list-mutators` | Lista todos los operadores de mutación disponibles (AOR, ROR, LCR, UOI). |
| `vassili doctor` | Verifica compiladores y suites de pruebas. |

````{tip}
Podés agregar el flag `--json` a la mayoría de los comandos para exportar resultados en formato estructurado o `--md` para generar reportes Markdown para el informe de entrega.
````

---

(manual-vassili-tutorial)=
## 4. Tutorial Paso a Paso con Ejemplos Reales

### Caso de Estudio

Considerá el siguiente fragmento de código representativo:

````{code-block} c
:linenos:
// Código original
int maximo(int a, int b) {
    if (a > b) return a;
    return b;
}

// Mutante #1 generado por Vassili (Operador Relacional ROR: '>' cambiado por '>=')
// Si tus tests no prueban el caso 'a == b', este mutante SOBREVIVE.
int maximo_mutante1(int a, int b) {
    if (a >= b) return a;
    return b;
}
````

### Ejecución de la Herramienta

Ejecutá el análisis desde tu terminal:

````{code-block} bash
vassili mutate src/calculadora.c --tests ./bin/test_suite
````

### Salida Obtenida en Consola

````{code-block} text
MUTATION TESTING REPORT (Vassili):
┌───────────────────────────┬────────┬───────────┐
│ Estado de Mutantes        │ Cant   │ Porcentaje│
├───────────────────────────┼────────┼───────────┤
│ Mutantes Asesinados (Killed)│ 42   │ 87.5%     │
│ Mutantes Vivos (Survived) │ 6      │ 12.5%     │
│ Mutantes Inválidos        │ 0      │ 0.0%      │
└───────────────────────────┴────────┴───────────┘
🎯 Mutation Score: 87.5% (Se recomienda > 80% para aprobación docente).
````

````{note}
Prestá atención a la explicación pedagógica generada: la herramienta no solo señala la línea del problema, sino que explica la causa raíz y el impacto en memoria o arquitectura.
````

---

(manual-vassili-ejercicios)=
## 5. Ejercicios Prácticos y Desafíos

Practicá el uso avanzado de **`vassili`** resolviendo los siguientes ejercicios:

````{exercise} Desafío 1: Cálculo de Mutation Score
Evaluar la suite de pruebas unitarias contra mutaciones en `src/tda_cola.c`.

**Instrucción de ejecución:**
```bash
vassili mutate src/tda_cola.c --tests ./bin/test_cola
```
````

````{solution} Desafío 1
```bash
vassili mutate src/tda_cola.c --tests ./bin/test_cola
# Verificá que la operación concluya exitosamente con código de salida 0.
```
````

````{exercise} Desafío 2: Identificación de Mutantes Vivos
Descubrir qué casos borde no están siendo testeados por la suite.

**Instrucción de ejecución:**
```bash
vassili report --survived-only
```
````

````{solution} Desafío 2
```bash
vassili report --survived-only
# Revisá el archivo generado o el informe en terminal para confirmar la resolución del problema.
```
````

````{exercise} Desafío 3: Generación de Informe HTML de Calidad
Exportar el informe gráfico con diffs de mutantes para revisión docente.

**Instrucción de ejecución:**
```bash
vassili report --format html -o mutaciones.html
```
````

````{solution} Desafío 3
```bash
vassili report --format html -o mutaciones.html
# Comprobá que la salida confirme la ausencia de advertencias o errores pendientes.
```
````

---

(manual-vassili-makefile)=
## 6. Integración en el Flujo de Trabajo y Makefile

Para incorporar `vassili` de forma automática a tu flujo de desarrollo, agregá la siguiente regla en el `Makefile` de tu proyecto:

````{code-block} makefile
check-vassili:
	@echo "=== Ejecutando verificación con vassili ==="
	vassili check src/ include/

.PHONY: check-vassili
````

Ejecutá `make check-vassili` antes de cada commit para asegurar que tu código conserve el estado de aprobación.
