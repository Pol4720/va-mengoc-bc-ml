# Informes de socialización (español)

| Documento | Para quién | Contenido |
|---|---|---|
| `informe_tecnico.tex` | Grupo de expertos | Datos, gobernanza, flujo de trabajo, resultados de ambos artículos, limitaciones, decisiones solicitadas |
| `resumen_ejecutivo.tex` | Dirección del IFV | Dos páginas: cifras clave, mensajes, decisiones y calendario |
| `kit_reuniones.tex` | Coordinación de las reuniones | Funciones, agenda tipo, preparación, registro de decisiones, plantilla de acta y seguimiento de acciones |

Todas las cifras proceden de las macros y tablas del release (`release/public` o, mientras no exista,
`release/synthetic` con la marca de agua *DATOS SINTÉTICOS*). Se compilan sin errores ni advertencias
con `python tools/latex_build.py` (los PDF quedan en `build/pdf/reports/`); la CI los publica como
artefacto `pdfs`.
