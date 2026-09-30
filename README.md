# VA-MENGOC-BC · Farmacovigilancia y calidad de lotes

Código reproducible, manuscritos y material de socialización de la línea de investigación sobre la
**vacuna antimeningocócica VA-MENGOC-BC** del Instituto Finlay de Vacunas (IFV), Dirección de
Investigaciones Clínicas y Evaluación de Impacto (DICEI) — grupo de ciencia de datos.

> **English summary.** Reproducible analytics for the Cuban outer-membrane-vesicle meningococcal B–C vaccine
> VA-MENGOC-BC: national passive AEFI surveillance 2017–2025 (reporting rates, READUS-PV disproportionality,
> latent reactogenicity phenotypes, hospitalisation models) and 15 years of lot-release quality control
> (capability, multivariate SPC, change points, destination equivalence) linked to post-marketing
> reactogenicity with a case-only, lot-clustered design. Restricted data never leave the controlled
> workstation; only disclosure-controlled aggregates are published.

## Líneas de publicación

| Paper | Pregunta | Diseño y métodos | Guía de reporte |
|---|---|---|---|
| **P1** — Vigilancia poscomercialización nacional (2017–2025) | ¿Cuál es el perfil de seguridad notificado de VA-MENGOC-BC en Cuba y ha cambiado en el tiempo? | Tasas de notificación por 100 000 dosis con IC exactos y tendencia (quasi-Poisson/BN); desproporcionalidad (ROR, PRR, IC-BCPNN, EBGM-MGPS) con comparador activo en lactantes y análisis de sensibilidad (coadministración, enmascaramiento); fenotipos latentes de reactogenicidad (LCA); correlatos de hospitalización (logística + LightGBM/SHAP con validación temporal) | READUS-PV, RECORD-PE |
| **P2** — Calidad de lote y reactogenicidad | ¿La variabilidad dentro de especificación de los lotes liberados se asocia al perfil de eventos notificados? | Capacidad de proceso (Ppk, IC bootstrap), gráficos EWMA y reglas de Nelson, PELT exacto, MSPC robusto (T² de Hotelling, SPE), equivalencia nacional/exportación (TOST, distancia energía); enlace notificación–lote; diseño *case-only* con GEE por lote, modelo mixto bayesiano, exposición control negativo, OR mínimo detectable y prueba de valor incremental por permutación | STROBE / RECORD-PE, TRIPOD+AI (componente ML) |

## Estructura

```
configs/            configuración versionada: pipeline, esquemas de columnas y diccionarios de normalización
src/vamengoc/       paquete Python (ingesta, curación, análisis, release, generador sintético, CLI, API local)
tests/              pruebas unitarias, de propiedades e integración (datos sintéticos)
data/               capas de datos restringidas — NUNCA versionadas (ver data/README.md)
release/            resultados públicos agregados con control de divulgación (synthetic/ y public/)
papers/             manuscritos LaTeX (EN/ES), material suplementario y paquete de envío
reports/            informes LaTeX de socialización (ES)
web/                aplicación web interactiva y presentaciones (GitHub Pages)
docs/               gobernanza de datos, preguntas abiertas, estrategia de publicación
tools/              guardas del repositorio (datos, releases, LaTeX)
```

## Flujo en dos fases

1. **Fase 1 — local, datos restringidos** (estación controlada del IFV):

   ```bash
   uv sync --all-extras
   uv run vamengoc keygen             # clave HMAC secreta, fuera del repositorio
   # copiar los ficheros originales a data/raw/ (solo lectura)
   uv run vamengoc schema-check       # valida la estructura de cada fichero antes de analizar
   uv run vamengoc run                # ingesta → curación → análisis → release/public
   uv run vamengoc release verify public
   ```

2. **Fase 2 — pública**: manuscritos, informes, presentaciones y web se construyen solo desde
   `release/public/` (revisado y confirmado por el responsable de datos). Mientras no exista, todo se
   construye desde `release/synthetic/` con la marca de agua **DATOS SINTÉTICOS**.

Detalles y requisitos de privacidad (seudonimización HMAC, minimización, ALCOA+, supresión de celdas
pequeñas, Ley 149/2022): [`docs/DATA_GOVERNANCE.md`](docs/DATA_GOVERNANCE.md).

## Desarrollo

```bash
uv sync --all-extras
uv run vamengoc demo --scale 0.3   # datos sintéticos de extremo a extremo
uv run pytest                      # pruebas + cobertura (umbral 90 %)
uv run ruff check src tests && uv run ruff format --check src tests && uv run mypy
uv run pre-commit install          # guardas locales en cada commit
```

## Autores

- Richard Alejandro Matos Arderí — Instituto Finlay de Vacunas, DICEI ·
  ORCID [0009-0008-0751-5855](https://orcid.org/0009-0008-0751-5855)
- Abel Ponce González — Instituto Finlay de Vacunas, DICEI ·
  ORCID [0009-0001-9200-4564](https://orcid.org/0009-0001-9200-4564)

## Licencia

Código bajo licencia MIT (`LICENSE`). Los datos de origen son confidenciales y **no** están cubiertos por
esta licencia; el contenido de `release/public/` se publica con fines científicos citando este repositorio.
