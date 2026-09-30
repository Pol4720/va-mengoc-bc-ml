# Contribuir

## Flujo de ramas

* `main` está protegida: solo recibe cambios mediante *pull request* con la CI en verde.
* Cada cambio en una rama corta (`feat/…`, `fix/…`, `paper/…`, `docs/…`), con commits pequeños y mensajes en
  imperativo (convención *Conventional Commits*: `feat:`, `fix:`, `docs:`, `test:`, `ci:`, `refactor:`).
* Los cambios que afectan a resultados publicados (configuración, diccionarios, métodos) se acompañan de la
  regeneración del release y de los documentos que lo citan.

## Antes de abrir un PR

```bash
uv run pre-commit run --all-files
uv run pytest
uv run mypy
make -C papers all          # manuscritos: 0 errores, 0 advertencias, 0 cajas mal ajustadas
```

## Reglas de datos

* Nunca se trabaja con datos reales fuera de la estación controlada; para desarrollar use `vamengoc demo`.
* Los números de los manuscritos provienen **siempre** de las macros generadas en `release/*/latex/`; nunca
  se escriben a mano.
* Cualquier nueva tabla publicada declara sus columnas de conteo de personas para que el control de
  divulgación y el verificador las cubran.
