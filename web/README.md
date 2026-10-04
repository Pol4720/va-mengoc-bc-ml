# Aplicación web VA-MENGOC-BC

React 19 + TypeScript + Vite + ECharts (renderizador SVG). Solo lee el bundle del release con control
de divulgación (`release/public/web/bundle.json` o, si no existe, `release/synthetic/web/bundle.json`),
que `npm run data` copia a `public/data/` (ignorado por git).

| Sección | Contenido |
|---|---|
| Inicio | Historia animada de los ocho pasos del pipeline y cifras principales |
| Farmacovigilancia | Tasas, puntos de cambio, desproporcionalidad con regla, diseño y mínimo ajustables, IC acumulado, fenotipos latentes, hospitalización |
| Calidad de lotes | Capacidad por periodo, cuantiles anuales, gráficos de control y EWMA, T², correlaciones, equivalencia, enlace, asociaciones y sensibilidad |
| Calidad de datos | Completitud, conformidad, plausibilidad, demora de notificación y contexto epidemiológico |
| Presentaciones | Tres presentaciones para las reuniones de expertos generadas desde el release |
| Laboratorio | Cliente de la API local (`uv run vamengoc serve`): parámetros, ejecución y carga del release verificado |

Diseño de visualización: paleta categórica validada para daltonismo en modo claro y oscuro, un solo
eje de valores por gráfico, líneas de 2 px, barras de 24 px como máximo, leyenda siempre que hay dos
series o más, vista de tabla y exportación CSV en cada figura, tooltips con el valor primero.

```bash
npm ci
npm run dev          # desarrollo
npm run lint         # ESLint (typescript-eslint, react-hooks)
npm run typecheck    # TypeScript estricto
npm test             # Vitest: datos, gráficos y prueba de humo de todas las páginas
npm run build        # producción en dist/
npx playwright test  # extremo a extremo: escritorio claro/oscuro y móvil
```

Con un Chromium ya instalado: `PW_CHROMIUM_PATH=/ruta/a/chrome npx playwright test`.
