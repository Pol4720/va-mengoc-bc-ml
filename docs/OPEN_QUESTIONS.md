# Preguntas abiertas al propietario de los datos

Estas preguntas condicionan decisiones del código y de los manuscritos. Cada respuesta debe
reflejarse en `configs/` (diccionarios versionados) y anotarse aquí con fecha y responsable.

| # | Pregunta | Decisión provisional en el código | Dónde se configura | Estado |
|---|---|---|---|---|
| 1 | Significado exacto de las siglas de TIPO DE VACUNA (AM-BC, PENTA-L, AG, AA, AL, AT…) y códigos de provincia | Investigado en fuentes públicas: AT = antitifoídica Vi («AT(vi)» del esquema cubano); PCV-10 = Pneumosil (Serum Institute of India, esquema desde 2024); Quimi-Vio (PCV7-TT) y SOBERANA son del Instituto Finlay; ABDALA, del CIGB. AA sigue sin confirmar | `configs/dictionaries/vaccines.yaml`, `geography.yaml` | Confirmar AA |
| 2 | Fecha que define el año de un registro; ¿los ficheros 2018–2025 tienen el mismo esquema? | Año analítico = año de F.VACUNACIÓN. Esquemas por año documentados: formulario antiguo 2017–2023, nuevo desde 2024; hoja maestra distinta por año; hojas de producto COVID-19 no se leen (ver `docs/DATA_ISSUES.md`) | `analysis.analytic_year_from`; `configs/schemas/aefi.yaml`; `inputs.aefi_*_sheet*` | Resuelta |
| 3 | Significado de la columna MES y de la columna final sin cabecera | MES (1–12 en todos los años) se usa como control de calidad y para saber qué meses cubre cada libro (años parciales); la columna sin cabecera se descarta y se informa | `curate/aefi_model.py` (`dq_month_mismatch`), `curate/rules.py` (`month_coverage`) | Confirmar |
| 4 | Clasificación de gravedad de cada evento; ¿existe codificación MedDRA/CIE-10? | Clasificación OMS (común/rara/grave) y definiciones Brighton cuando existen | `configs/dictionaries/events.yaml` | Pendiente |
| 5 | Vacuna exacta del fichero de lotes y semántica de "-" en Inocuidad | VA-MENGOC-BC; "-" = no determinado | `configs/schemas/lots.yaml` | Pendiente |
| 6 | Clave única de lote y motivo de los 22 identificadores duplicados | Un mismo lote aparece en varias filas (varios destinos o ensayos: 714 lotes en 737 filas). Clave compuesta `lote@año#n`; en el enlace se prefiere el lote nacional cuya vigencia cubre la vacunación | `ingest/lots.py`, `curate/linkage.py` | Resuelta |
| 7 | Base legal, autorización ética y política de retención; ¿se requiere evaluación de impacto en la privacidad? | Tratamiento local seudonimizado; release agregado con control de divulgación | `docs/DATA_GOVERNANCE.md` | Pendiente |
| 8 | Dosis aplicadas de VA-MENGOC-BC en los años recientes (denominador) | Un año sin dosis no tiene tasa; un año con menos de 12 meses de datos (2023, el año en curso) tampoco | hoja de cobertura | Confirmar |
| 9 | ¿Qué atributos de calidad pueden publicarse en unidades absolutas? | Solo posición normalizada en la ventana de especificación e índices adimensionales | `sdc.release_lot_values` | Pendiente |
| 10 | Tasa esperada de referencia del programa (50 por 100 000 dosis) | Tomada de Cruz-Rodríguez et al. (2021) | `analysis.expected_national_rate_per_100k` | Confirmar |
| 11 | Equivalencias entre el formulario usado desde 2024 y el anterior: ¿FIEBRE corresponde a FIEBRE 39, a FIEBRE 40 o a ninguna?; ¿ABSCESO es estéril, bacteriano o ambos?; ¿ANAFILAXIA = R. ANAFILÁCTICA?; ¿TROMBOCITOPENIA = PÚRPURA?; ¿desaparecieron R.L.S., LLANTO PERSISTENTE y los demás indicadores anteriores o cambiaron de nombre?; significado de APP CI y de la columna APP | Cada indicador se trata como distinto y se analiza solo en los ficheros que lo registran (`recorded_mask`); un indicador ausente de un año es desconocido, no "no notificado". Si se confirma una equivalencia, basta con añadir el nuevo encabezado como alias del campo anterior | `configs/schemas/aefi.yaml`, `configs/dictionaries/events.yaml` (`expected`) | Pendiente |
| 12 | Nombre exacto de la columna de IgG (ELISA) en el libro de lotes y unidades | «Inmunogenicidad (Activ. Antic. IgG) (UIgG/mL)»: reconocido por patrón; los atributos siguen siendo opcionales uno a uno | `configs/schemas/lots.yaml` (alias o `patterns`) | Resuelta |
| 13 | Uso del CARNÉ DE IDENTIDAD (formulario desde 2024) | Identificador directo: se reconoce y se descarta; no se usa para el seudónimo, que sigue siendo nombre + fecha de nacimiento + sexo en todos los años | `configs/schemas/aefi.yaml` (`national_id`) | Confirmar |
| 14 | Comparador del artículo 1 | Solo vacunas del Instituto Finlay; las demás entran como concomitantes (acordado con la jefa del proyecto) | `analysis.comparator` | Resuelta |
| 15 | Notificaciones con lotes vencidos (filas copiadas) | El primer dígito del lote es la última cifra del año de liberación y la vigencia es de 3 años; se excluyen del artículo 2 y su proporción decide su factibilidad | `analysis.linkage`, `analysis.p2_feasibility` | Resuelta |
| 16 | Edades que violan el esquema de VA-MENGOC-BC | Esquema 3 y 5 meses; se excluyen las dosis por debajo de la edad mínima o inexistentes; adelantadas válidas, tardías y refuerzos de campaña se conservan | `analysis.schedule` | Resuelta |
| 17 | Entregas mensuales y datos de 2026 | Ventana abierta (`study_years: [2017, null]`); meses no cubiertos = ausentes; años parciales sin tasa anual | `analysis.study_years` | Resuelta |

Las reglas y su justificación están en [`DATA_ISSUES.md`](DATA_ISSUES.md); la ejecución local y la
entrega de resultados, en [`RUN_LOCAL.md`](RUN_LOCAL.md).
