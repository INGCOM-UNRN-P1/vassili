# VASSILI — Motor de Mutation Testing en C

> 📖 **Manual de Usuario:** Para una guía exhaustiva de comandos, banderas, arquitectura y ejemplos, consultá el [Manual de Uso](MANUAL.md).

**VASSILI** evalúa la calidad y exhaustividad real de las suites de prueba de los estudiantes mediante la inyección procedural de mutantes sintéticos en el código fuente C (operadores aritméticos, relacionales y lógicos) y calcula el **Mutation Score** (% de mutantes detectados).

---

## 🎯 Alcance

### Qué cubre
- Motor de Mutation Testing para código fuente C y evaluación de calidad de suites de pruebas.
- Aplicación de operadores de mutación por **sustitución textual** línea a línea (no sobre un AST): inversión de comparaciones, mutación de operadores aritméticos y cambio de conectores lógicos. Antes de mutar se enmascaran comentarios y literales de cadena/carácter, así que un `+` dentro de un `"..."` no se toca. No muta literales numéricos ni constantes.
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

- **`AOR`** (Arithmetic Operator Replacement): `+` ➔ `-`, `-` ➔ `+`, `*` ➔ `/` (el `*` de puntero o desreferencia no se muta).
- **`ROR`** (Relational Operator Replacement): `==` ➔ `!=`, `!=` ➔ `==`, `<` ➔ `<=`, `<=` ➔ `>`, `>` ➔ `>=`, `>=` ➔ `<`.
- **`LCR`** (Logical Connector Replacement): `&&` ➔ `||` y `||` ➔ `&&`.

<!-- p1:referencia:inicio — generado por p1-tools/scripts/readme_generado.py: no editar a mano -->

## Referencia rápida

### Requisitos

- Python ≥ 3.11 y [uv](https://docs.astral.sh/uv/getting-started/installation/).
- Programas del sistema: `gcc`.

| Sistema | `gcc` |
|:--|:--|
| Debian / Ubuntu | `sudo apt install gcc` |
| Fedora | `sudo dnf install gcc` |
| Windows | incluido en el entorno de la cátedra (MSYS2 UCRT64) |
| macOS | `xcode-select --install` (clang como `gcc`) |

### Comandos

| Comando | Descripción |
|:--|:--|
| `vassili check`, `vassili mutate` | Genera mutantes sintéticos del código C y evalúa qué porcentaje es detectado por los tests. |
| `vassili report` | Genera directamente la sección de reporte Markdown de VASSILI para Dredd. |
| `vassili version` | Muestra la versión de VASSILI. |
| `vassili doctor` | Verifica el estado del entorno de VASSILI (Python, GCC). |

Ayuda de cada comando: `vassili <comando> -h`.

### Salida JSON

Con `--json`, estos comandos emiten el resultado como JSON por la salida estándar, para usarlo desde scripts, ripley o dredd: `vassili check`, `vassili mutate`, `vassili doctor`. El de `doctor --json` lleva `schema_version` y `ok`.

### Códigos de salida

| Código | Significado |
|:--|:--|
| `0` | Terminó bien (en `doctor`: está todo lo requerido). |
| `1` | El comando encontró problemas (hallazgos, pruebas que fallan, un umbral que no se alcanza) o un dato no se pudo usar (un archivo ilegible, un formato inválido). |
| `2` | Error de uso: comando, opción o argumento inválido. |

<!-- p1:referencia:fin -->
