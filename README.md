# VASSILI — Motor de Mutation Testing en C

> 📖 **Manual de Usuario:** Para una guía exhaustiva de comandos, banderas, arquitectura y ejemplos, consultá el [Manual de Uso](MANUAL.md).

**VASSILI** evalúa la calidad y exhaustividad real de las suites de prueba de los estudiantes mediante la inyección procedural de mutantes sintéticos en el código fuente C (operadores aritméticos, relacionales y lógicos) y calcula el **Mutation Score** (% de mutantes detectados).

---

## 🎯 Alcance

### Qué cubre
- Motor de Mutation Testing para código fuente C y evaluación de calidad de suites de pruebas.
- Aplicación de operadores de mutación por **sustitución textual** línea a línea (no sobre un AST): inversión de comparaciones, operadores aritméticos, incrementos, conectores y negaciones lógicas, retornos constantes y, con `--sanitizers`, reservas de memoria y liberaciones. Antes de mutar se enmascaran comentarios y literales de cadena/carácter, así que un `+` dentro de un `"..."` no se toca. No muta literales numéricos salvo los de un `return`.
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
- Extra `ecosistema`: `daedalus` compila los mutantes y `nostromo` los ejecuta aislados.

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
- **`UOI`** (Unary Operator Increment): `++` ➔ `--` y `--` ➔ `++`; junto con `<` ➔ `<=` revela los errores de borde de los lazos.
- **`LNR`** (Logical Negation Removal): `!condicion` ➔ `condicion`.
- **`RVR`** (Return Value Replacement): `return 0;` ➔ `return 1;` y cualquier otra constante ➔ `return 0;` (no en `main`, donde solo cambiaría el código de salida).
- **`MSR`** (Memory Size Reduction, solo con `--sanitizers`): `malloc(tam)` ➔ `malloc((tam) - 1)`.
- **`FDR`** (Free Deletion, solo con `--sanitizers`): `free(p)` ➔ `(void)0`, una fuga.

`MSR` y `FDR` solo se generan con `--sanitizers`, que compila y corre con AddressSanitizer: sin
él ningún test puede detectar una reserva de menos o una fuga, y esos mutantes bajarían el score
sin culpa de la suite.

Además:

- **Equivalentes:** si un mutante compila (con `-O2`) al mismo código objeto que el original,
  ningún test puede distinguirlo; se marca `equivalent` y queda fuera del score.
- **Aislamiento:** cada corrida es un proceso aparte con límite de tiempo, de CPU, de memoria
  (512 MB) y de salida (8 MB): un mutante con un bucle infinito o que imprime sin parar no
  cuelga el análisis. Con el extra `ecosistema` corre además dentro del sandbox de `nostromo`
  (bwrap: sin red y sin escribir fuera de él), así que un mutante que borra o pisa archivos no
  toca la máquina del evaluador. El reporte dice cuál se usó (`aislamiento`).
- **Qué caso falta:** de cada mutante que sobrevive se sugiere el caso de prueba que lo mataría
  (en la tabla, el JSON —`sugerencia`— y la sección Markdown).

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
