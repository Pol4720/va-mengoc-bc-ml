# data/ — capas de datos (nunca se versionan)

| Carpeta | Contenido | Quién la escribe |
|---|---|---|
| `raw/` | Ficheros originales `EA_<AÑO>_TOTAL.xlsx` y `BD_para_publicación_lotes_final.xlsx`, **solo lectura** | El responsable de datos (copia manual desde el repositorio institucional) |
| `interim/` | Reservada para capas intermedias tipadas | Pipeline |
| `curated/` | Modelo relacional seudonimizado (parquet, opcionalmente cifrado) | `vamengoc run` |
| `synthetic/` | Datos simulados para desarrollo y demostración | `vamengoc synth` / `vamengoc demo` |

El `.gitignore`, el hook de pre-commit (`tools/check_no_data.py`) y la CI impiden que cualquier fichero de
estas carpetas llegue a git. Ver [`docs/DATA_GOVERNANCE.md`](../docs/DATA_GOVERNANCE.md).
