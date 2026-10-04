# Gobernanza de datos y flujo en dos fases

Este documento define cómo se tratan los datos personales de salud (notificaciones de ESAVI/EA) y la
información industrial confidencial (liberación de lotes) en el proyecto. Se aplica a todas las personas
que ejecuten el código. Resume buenas prácticas reconocidas: principios ALCOA+ de integridad de datos
(MHRA 2018; FDA 2018), Buenas Prácticas Clínicas ICH E6(R3) (2025), seudonimización con clave secreta
(ENISA 2019), control estadístico de la divulgación (Hundepool et al., 2012) y la Ley 149/2022 de
Protección de Datos Personales de la República de Cuba.

## 1. Clasificación de la información

| Nivel | Contenido | Dónde vive | ¿Se versiona? |
|---|---|---|---|
| **Restringido – personal de salud** | Ficheros `EA_<AÑO>_TOTAL.xlsx` (nombres, direcciones, fechas de nacimiento, eventos, texto libre) | `data/raw/` en la estación controlada | **Nunca** |
| **Restringido – industrial** | `BD_para_publicación_lotes_final.xlsx` (valores de control de calidad por lote) | `data/raw/` | **Nunca** |
| **Interno seudonimizado** | Capa *curated* (parquet, opcionalmente cifrada), manifiestos de ejecución | `data/curated/`, `runs/` | **Nunca** |
| **Público** | Estadísticos agregados con control de divulgación, figuras, macros, bundle web | `release/public/` | Sí, tras revisión |
| **Sintético** | Datos simulados y su release, sin relación con personas reales | `data/synthetic/`, `release/synthetic/` | Solo el release |

El `.gitignore` bloquea cualquier hoja de cálculo, base de datos, parquet o clave en todo el repositorio;
el hook de *pre-commit* y la CI vuelven a comprobarlo (`tools/check_no_data.py`).

## 2. Fase 1 — procesamiento local (datos restringidos)

Se ejecuta **solo** en la estación autorizada del IFV, sin conexión de los datos a servicios externos
ni a modelos de lenguaje:

```bash
uv sync                          # entorno reproducible (uv.lock)
uv run vamengoc keygen           # una vez: clave HMAC fuera del repositorio (~/.config/vamengoc)
cp /ruta/segura/*.xlsx data/raw/ # los originales se conservan inmutables (solo lectura)
uv run vamengoc schema-check     # verifica la estructura de cada fichero antes de analizar
uv run vamengoc run              # ingesta → curación → análisis → release/public
uv run vamengoc release verify public
```

Lo que ocurre internamente:

1. **Lectura sin inferencia de tipos.** Cada celda se conserva tal cual y se tipa con analizadores
   explícitos que registran el estado de cada valor (`ok`, `recovered`, `invalid`, `missing`,
   `not_applicable`).
2. **Seudonimización en memoria.** Nombre y dirección se usan solo para derivar un identificador
   HMAC-SHA256 con clave secreta y se descartan; nunca se escriben en disco, registros ni salidas.
   Sin clave, una ejecución sobre datos reales se niega a arrancar; la clave pública de prueba
   (solo para datos sintéticos) es rechazada con datos reales.
3. **Minimización.** La fecha de nacimiento se transforma en edad; el texto libre "CUAL (otro)" se
   transforma en categorías y el texto se descarta.
4. **Trazabilidad ALCOA+.** Cada ejecución registra operador, fecha UTC, versión del código (commit y
   estado), versiones de librerías, semilla, SHA-256 de cada fichero de entrada y de configuración, y
   el número de filas en cada transformación (`runs/<run_id>/manifest.json`, `runs/audit.jsonl`).
5. **Cifrado en reposo opcional** de la capa *curated* (Fernet) con `security.encrypt_curated: true`.
   El cifrado de disco de la estación sigue siendo el control principal.

## 3. Control estadístico de la divulgación (release público)

El release es el único artefacto que sale de la estación controlada. Reglas aplicadas automáticamente:

* conteos de personas entre 1 y `min_cell − 1` (por defecto 1–4) → `"<5"`;
* porcentajes, tasas, razones y estimaciones derivadas de un conteo suprimido → eliminados;
* supresión complementaria (marca `[c]`, distinta de `"<5"` porque no son conteos pequeños) cuando un
  conteo suprimido podría recuperarse por diferencia: tablas de contingencia con márgenes, series
  anuales o mensuales cuyos totales se publican en otra tabla, y celdas de un mismo nivel por grupos;
* no se publica el grupo «Todas» (= diana + otras) en las tablas por grupo: los documentos lo recalculan
  solo cuando ambos grupos son visibles; tampoco se publican variables que son agrupaciones de otras ya
  publicadas (p. ej., grupo de edad frente a banda de edad);
* en la tabla 2×2 de desproporcionalidad solo se publica `a`; `b`, `c` y `d` se sustituyen por los
  tamaños de cada diseño (`p1_design_sizes`), porque con los totales revelarían un `a` suprimido;
* los diseños de sensibilidad (subconjuntos del principal), las series acumuladas y los análisis
  restringidos se retienen cuando difieren del principal o del valor anterior en un conteo pequeño;
* los porcentajes y proporciones publicados sin su conteo se eliminan cuando implican un conteo
  pequeño (o su complemento lo es);
* sin fechas con precisión de día; geografía máxima: región o provincia agregada;
* sin identificadores (ni seudónimos), texto libre, lotes originales ni valores de control de calidad en
  unidades absolutas (por defecto, `sdc.release_lot_values: normalized` expresa cada valor como posición
  en la ventana de especificación).

`vamengoc release verify public` comprueba tipos de fichero, columnas y patrones prohibidos, conteos
pequeños, fechas, integridad (SHA-256 del manifiesto) y coherencia del origen. La CI lo repite en cada
push y el *pre-commit* impide confirmar un release que no lo supere.

## 4. Fase 2 — redacción y socialización (datos públicos)

Los manuscritos, informes, presentaciones y la aplicación web se construyen **solo** a partir de
`release/public/` (o de `release/synthetic/`, en cuyo caso todos los documentos muestran la marca de agua
*DATOS SINTÉTICOS*). El equipo de redacción, los revisores y los colaboradores externos trabajan con
este nivel de información, que es el que se publica.

## 5. Revisión humana antes de publicar el release

Antes de confirmar `release/public/` en git, el responsable de datos:

1. revisa `release/public/README.md` y el registro de supresión del `manifest.json`;
2. comprueba los riesgos que las reglas automáticas no cubren por completo: combinaciones de tablas
   con subgrupos anidados distintos de los previstos, eventos graves o raros que puedan identificar a
   una persona en una provincia o año concretos, y cualquier tabla nueva añadida al release;
3. confirma que las tablas de lotes no revelan información industrial no autorizada;
4. ejecuta `uv run vamengoc release verify public` (debe terminar sin errores);
5. firma el commit con su identidad institucional.

Confirmar `release/public/` equivale a publicarlo: la aplicación web de GitHub Pages
(`.github/workflows/pages.yml`) copia su `web/bundle.json` y nada más. Mientras no exista, el sitio
muestra el release sintético con la advertencia *Datos sintéticos* en todas las páginas. El
laboratorio de la aplicación nunca envía datos a Internet: llama a la API local
(`uv run vamengoc serve`, solo 127.0.0.1, con token de sesión) y recibe únicamente un release
verificado.

## 6. Retención y acceso

* `data/raw/`: copia de trabajo; el original permanece en el repositorio institucional de la DICEI.
* `data/curated/` y `runs/`: se eliminan al cerrar cada ciclo de análisis o tras 12 meses.
* Acceso restringido al equipo de ciencia de datos de la DICEI; las claves se custodian por separado.

## 7. Preguntas abiertas al propietario de los datos

Ver [`OPEN_QUESTIONS.md`](OPEN_QUESTIONS.md). Las respuestas se reflejan en los diccionarios
versionados de `configs/` y quedan registradas en el historial de git.
