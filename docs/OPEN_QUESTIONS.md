# Preguntas abiertas al propietario de los datos

Estas preguntas condicionan decisiones del código y de los manuscritos. Cada respuesta debe
reflejarse en `configs/` (diccionarios versionados) y anotarse aquí con fecha y responsable.

| # | Pregunta | Decisión provisional en el código | Dónde se configura | Estado |
|---|---|---|---|---|
| 1 | Significado exacto de las siglas de TIPO DE VACUNA (AM-BC, PENTA-L, AG, AA, AL, AT…) y códigos de provincia | Mapeos marcados `confidence: inferred` | `configs/dictionaries/vaccines.yaml`, `geography.yaml` | Pendiente |
| 2 | Fecha que define el año de un registro; ¿los ficheros 2018–2025 tienen el mismo esquema? | Año analítico = año de F.VACUNACIÓN; el esquema se valida fichero a fichero | `analysis.analytic_year_from`; `configs/schemas/aefi.yaml` | Pendiente |
| 3 | Significado de la columna MES y de la columna final sin cabecera | MES solo se usa como control de calidad; la columna sin cabecera se descarta y se informa | `curate/aefi_model.py` (`dq_month_mismatch`) | Pendiente |
| 4 | Clasificación de gravedad de cada evento; ¿existe codificación MedDRA/CIE-10? | Clasificación OMS (común/rara/grave) y definiciones Brighton cuando existen | `configs/dictionaries/events.yaml` | Pendiente |
| 5 | Vacuna exacta del fichero de lotes y semántica de "-" en Inocuidad | VA-MENGOC-BC; "-" = no determinado | `configs/schemas/lots.yaml` | Pendiente |
| 6 | Clave única de lote y motivo de los 22 identificadores duplicados | Clave compuesta `lote@año#n`; en el enlace se prefiere lote nacional y año de producción más reciente ≤ año de vacunación | `ingest/lots.py`, `curate/linkage.py` | Pendiente |
| 7 | Base legal, autorización ética y política de retención; ¿se requiere evaluación de impacto en la privacidad? | Tratamiento local seudonimizado; release agregado con control de divulgación | `docs/DATA_GOVERNANCE.md` | Pendiente |
| 8 | Dosis aplicadas de VA-MENGOC-BC en 2025 (denominador) | Tasas 2025 no calculadas | hoja de cobertura | Pendiente |
| 9 | ¿Qué atributos de calidad pueden publicarse en unidades absolutas? | Solo posición normalizada en la ventana de especificación e índices adimensionales | `sdc.release_lot_values` | Pendiente |
| 10 | Tasa esperada de referencia del programa (50 por 100 000 dosis) | Tomada de Cruz-Rodríguez et al. (2021) | `analysis.expected_national_rate_per_100k` | Confirmar |
| 11 | Equivalencias entre el formulario usado desde 2024 y el anterior: ¿FIEBRE corresponde a FIEBRE 39, a FIEBRE 40 o a ninguna?; ¿ABSCESO es estéril, bacteriano o ambos?; ¿ANAFILAXIA = R. ANAFILÁCTICA?; ¿TROMBOCITOPENIA = PÚRPURA?; ¿desaparecieron R.L.S., LLANTO PERSISTENTE y los demás indicadores anteriores o cambiaron de nombre?; significado de APP CI y de la columna APP | Cada indicador se trata como distinto y se analiza solo en los ficheros que lo registran (`recorded_mask`); un indicador ausente de un año es desconocido, no "no notificado". Si se confirma una equivalencia, basta con añadir el nuevo encabezado como alias del campo anterior | `configs/schemas/aefi.yaml`, `configs/dictionaries/events.yaml` (`expected`) | Pendiente |
| 12 | Nombre exacto de la columna de IgG (ELISA) en el libro de lotes y unidades | Los atributos de calidad son opcionales uno a uno; si no se reconoce, se analiza sin él y `schema-check` lo lista | `configs/schemas/lots.yaml` (alias o `patterns`) | Pendiente |
| 13 | Uso del CARNÉ DE IDENTIDAD (formulario desde 2024) | Identificador directo: se reconoce y se descarta; no se usa para el seudónimo, que sigue siendo nombre + fecha de nacimiento + sexo en todos los años | `configs/schemas/aefi.yaml` (`national_id`) | Confirmar |
