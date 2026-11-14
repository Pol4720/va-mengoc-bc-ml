# Ejecución local con los datos reales y entrega de resultados

Guía paso a paso para la estación controlada. Ningún dato individual sale de ella: solo se sube la
carpeta `release/public/`, que contiene agregados con control de divulgación.

## 0. Una sola vez

```bash
git clone https://github.com/Pol4720/va-mengoc-bc-ml.git && cd va-mengoc-bc-ml
uv sync --all-extras
uv run vamengoc keygen          # clave HMAC secreta en ~/.config/vamengoc/hmac.key (no la comparta)
```

Guarde una copia de seguridad de la clave fuera del equipo: sin ella los seudónimos de corridas
futuras no coinciden con los anteriores.

## 1. Cada entrega (mensual)

1. Actualice el código: `git pull`.
2. Copie a `data/raw/` (carpeta ignorada por git, nunca se sube):
   * los libros anuales `EA <año> TOTAL.xlsx` (2017 en adelante, incluido el del año en curso);
   * el libro de lotes `BD para publicación lotes final.xlsx`.

   Si llega una versión acumulada nueva del año en curso, **sustituya** la anterior (no deje dos
   versiones del mismo año). Meses entregados en ficheros separados sí pueden convivir.
3. Compruebe la estructura (solo imprime títulos de columnas, nunca valores):

   ```bash
   uv run vamengoc schema-check
   ```

   Revise las columnas «unmatched» y «missing required». Un título nuevo se resuelve añadiéndolo
   como alias en `configs/schemas/aefi.yaml` o `configs/schemas/lots.yaml`.
4. Ejecute el análisis completo:

   ```bash
   uv run vamengoc run
   ```

   Al final se imprime la tabla «Data problems handled in this run» (años analizados, años
   parciales, fechas corregidas, dosis fuera de esquema, comparador Finlay, lotes vencidos) y el
   veredicto del artículo 2 (`adequate`, `limited` o `insufficient`; ver `docs/DATA_ISSUES.md`).
   La verificación de divulgación debe terminar en «Release verified … no disclosure problems».
5. (Opcional) Revise los PDF localmente: `python tools/latex_build.py` y la web con
   `uv run vamengoc serve`.

## 2. Entregar los resultados para completar la redacción

1. Revise `release/public/` (CSV, JSON, figuras, macros LaTeX). Es lo único que se publica.
2. Súbalo en una rama y abra un pull request:

   ```bash
   git checkout -b release/public-$(date +%Y-%m)
   uv run vamengoc release verify public
   git add release/public
   git commit -m "release: public results $(date +%Y-%m)"
   git push -u origin HEAD
   ```

   Los guardas del repositorio impiden subir `data/`, claves o ficheros con columnas prohibidas.
3. Con `release/public/` en el repositorio, los manuscritos, informes, presentaciones y la web se
   construyen automáticamente con los resultados reales (sin la marca DATOS SINTÉTICOS) y el ciclo
   de redacción se completa sobre ese release: cada cifra de los artículos es una macro generada.

## 3. Si algo falla

| Síntoma | Qué hacer |
|---|---|
| `SchemaError: required fields missing` | `schema-check` muestra el título no reconocido; añádalo como alias. |
| `Release verification FAILED` | No suba nada; copie el mensaje (no contiene datos) y abra un issue. |
| Veredicto `insufficient` del artículo 2 | Es un resultado: los datos de lote no sustentan el artículo 2 y el manuscrito lo declara. |
| Muchas «dosis fuera del esquema» | Revise `tables/p1_schedule.json`; si el esquema nacional difiere, ajuste `analysis.schedule`. |
| Regla de lotes «not validated» | El código de lote no reproduce el año del libro; revise `tables/p2_lot_validity.json`. |
