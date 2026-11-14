# Problemas conocidos de los datos y reglas aplicadas

Cada regla está en el código y en `configs/pipeline.yaml`; los recuentos se publican solo agregados
(celdas menores que 5 suprimidas) en `release/<origen>/tables/` y los manuscritos los citan como
macros, de modo que el texto nunca contradice los datos.

## 1. Lotes vencidos (filas copiadas sin actualizar el LOTE) — afecta solo al artículo 2

**Problema.** Los operadores copian y pegan filas y no siempre actualizan el número de lote: la
notificación queda con el lote de otra vacunación.

**Regla de codificación.** El primer dígito del código de un lote es la última cifra del año en que
se liberó (un lote de 2001 o de 2011 empieza por 1), y un lote tiene una vigencia de 3 años. Dada la
fecha de vacunación, el año de liberación es el último año, no posterior a la vacunación, cuya cifra
final coincide con el código (`curate/lot_validity.py`). Estado de cada notificación con un lote de
VA-MENGOC-BC:

| Estado | Condición |
|---|---|
| `valid` | año de liberación ≤ año de vacunación ≤ año de liberación + 3 |
| `expired` | vacunación posterior al fin de la vigencia |
| `before_release` | vacunación anterior a la liberación (solo posible con el año del libro de lotes) |
| `not_assessable` | sin lote, o con varios lotes distintos, o código sin dígitos |

La regla se contrasta con el libro de lotes (que registra el año de producción): debe reproducir el
año de producción o el siguiente en al menos el 90 % de los lotes (`linkage.code_year_min_agreement`).
Si no lo hace, el pipeline avisa y usa el año del libro para los lotes enlazados.

**Decisión.** Una notificación con un lote vencido o aún no liberado no puede llevar el lote
administrado: se excluye de los análisis por lote y se conserva en un análisis de sensibilidad. Su
proporción es una **cota inferior** del error del campo de lote (las copias que quedan dentro de la
vigencia no se detectan), y decide si el artículo 2 es sustentable (`analysis.p2_feasibility`):

| Proporción de lotes imposibles | Veredicto | Consecuencia |
|---|---|---|
| ≤ 10 % | `adequate` | análisis por lote respaldado |
| 10–20 % | `limited` | respaldado con una limitación declarada |
| > 20 %, o < 200 notificaciones válidas enlazadas, o < 30 lotes | `insufficient` | **no hay información suficiente para sustentar el artículo 2**: el manuscrito lo declara automáticamente (`\PTFeasibilitySentence`, `\PTConclusionSentence`) y los resultados por lote se presentan solo por transparencia |

El veredicto se imprime al final de `vamengoc run` y queda en `tables/p2_feasibility.json`.

## 2. Edades que violan el esquema de vacunación — artículos 1 y 2

**Esquema** (`analysis.schedule`): VA-MENGOC-BC dosis 1 a los 3 meses y dosis 2 a los 5 meses
(Sierra-González, MEDICC Rev 2019); válida desde los 3 meses, dos dosis separadas 6–8 semanas, sin
refuerzo en el uso programado (prospecto del producto). Edades mínimas con el período de gracia de
4 días de las guías ACIP (Kroger et al., 2023): 2,87 meses para la dosis 1 y 4,25 meses para la 2.

| Categoría | Decisión |
|---|---|
| En el esquema, adelantada (≥ edad mínima), tardía (recuperación), refuerzo de campaña | se conserva |
| Por debajo de la edad mínima, número de dosis inexistente (3, 4…) | **se excluye** (error de registro de vacuna, dosis o edad) y se conserva en un diseño de sensibilidad |

Una edad registrada solo en meses enteros («2M») recibe el beneficio de la duda: se considera
demasiado joven solo si incluso el límite superior (2,99 meses) queda por debajo del mínimo. Cuando
hay fecha de nacimiento válida, la edad se calcula con las fechas (ya corregidas, punto 3).

## 3. Fechas imposibles — imputación lógica

Cada libro anual contiene las notificaciones de su año, que pueden referirse a vacunaciones del año
anterior. Un año de vacunación fuera de [año del libro − 1, año del libro] o de notificación fuera de
[año del libro − 1, año del libro + 1] es un error de tecleo (2029 o 2002 en el libro de 2019). Se
corrige **solo** cuando el día y el mes se conservan y la otra fecha y el año del libro determinan el
año con una demora coherente (0–365 días); si hay varias opciones, la de menor demora. Si no hay
corrección coherente, la fecha se descarta (no se usa) y el año analítico pasa a la otra fecha o al
año del libro (`parsing/dates.py::repair_report_dates`). La edad se recalcula después.
Las fechas de nacimiento imposibles (1699, 2075…) no se corrigen: se ignoran y se usa la edad
registrada.

## 4. Comparador del artículo 1

Acordado con la jefa del proyecto VA-MENGOC-BC: la comparación (influencia) es solo con las vacunas
propias del Instituto Finlay o con los tratamientos concomitantes (`analysis.comparator`). Productos
Finlay del diccionario (`configs/dictionaries/vaccines.yaml`): DPT, DT/dT, TT, AT (antitifoídica Vi),
vax-SPIRAL (AL), vax-TyVi, Quimi-Vio (PCV7-TT) y SOBERANA. Investigado en fuentes públicas: PCV-10 en
2024–2025 es Pneumosil (Serum Institute of India, esquema de 2024) y ABDALA es del CIGB; no son
comparadores. Las vacunas de otros fabricantes solo entran como concomitantes: el diseño
`concomitant_influence` compara, dentro de VA-MENGOC-BC, las notificaciones con vacunas
coadministradas frente a VA-MENGOC-BC sola.

## 5. Estructura de los libros

* Hoja maestra: la de nombre preferido o que contiene «TOTAL»; si hay varias, la de más filas.
* Hojas de producto (ABDALA, SOBERANA… en 2021–2024) son copias de la maestra: **no se leen**.
* La hoja «Casos que no entraron en el cierre» (2018) se lee además de la maestra; las filas
  repetidas se eliminan en la deduplicación.
* Desde 2024 el formulario cambió (DOLOR, ENROJECIMIENTO, INDURACIÓN en una sola columna, GRAVE/NO
  GRAVE, CARNÉ DE IDENTIDAD): cada indicador se analiza solo en los ficheros que lo registran.

## 6. Datos mensuales y años incompletos (2023, 2026…)

* `analysis.study_years: [2017, null]`: el último año sigue a los datos; un libro nuevo
  (`EA 2026 TOTAL.xlsx`) entra sin editar la configuración.
* Un mes está observado si el libro de su año tiene notificaciones de ese mes (columna MES o mes de
  notificación) en cantidad no anecdótica (≥ 10 % de la mediana mensual del libro). Los meses no
  cubiertos son **ausentes**, no ceros: las series mensuales los dejan en blanco y los puntos de
  cambio se buscan solo en meses observados.
* Un año con menos de 12 meses observados es **parcial**: sus notificaciones se analizan, pero no
  tiene tasa anual ni entra en la tendencia (`\VPartialYearsSentence`).
* Varias entregas del mismo año: si son meses distintos se combinan; si son versiones acumuladas,
  conserve en `data/raw/` solo la más reciente (`schema-check` lo advierte).
