# Seguridad y protección de datos

## Qué nunca debe entrar al repositorio

Ficheros de datos de origen o curados, claves (`hmac.key`, `fernet.key`, `.env`), manifiestos de ejecución
(`runs/`) y cualquier tabla con registros individuales. El `.gitignore`, `tools/check_no_data.py` (pre-commit y
CI) y `vamengoc release verify` lo impiden; no desactive estas guardas.

## Si ocurre una exposición accidental

1. No haga más commits sobre la rama afectada; avise al responsable de datos de la DICEI.
2. Considere comprometidas las claves de seudonimización y regenérelas (`vamengoc keygen --force`); los
   identificadores antiguos quedan invalidados.
3. Elimine el contenido del historial con `git filter-repo` y solicite a GitHub la purga de cachés.
4. Documente el incidente según el procedimiento institucional y la Ley 149/2022.

## Reporte de vulnerabilidades

Comunique cualquier vulnerabilidad del código de forma privada a los autores (ver `CITATION.cff`), no en
issues públicos.
