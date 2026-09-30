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
