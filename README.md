# RepoHealthChecker

CLI de Python 3.11+ para auditar **indicadores de mantenimiento y buenas prácticas** de repositorios GitHub. Solo realiza consultas `GET` a la API REST; no modifica repositorios.

## Instalación

Desde la carpeta del proyecto:

```bash
python -m pip install .
```

Alternativamente, sin instalar dependencias:

```bash
python -m repohealthchecker --help
python -m repohealthchecker Rigor-Core/fudi
```

Para ejecutar el comando `repohealthchecker` directamente, instala el paquete como se indicó. El único requisito de ejecución es Python 3.11 o superior; la instalación mediante pip usa setuptools para construir el paquete.

## Uso

```bash
repohealthchecker owner/repo
repohealthchecker https://github.com/owner/repo
repohealthchecker owner/repo --format json
repohealthchecker owner/repo --format json --output informe.json
repohealthchecker owner/repo --fail-under 80
```

Opciones: `--format text|json`, `--output RUTA`, `--fail-under 0-100`, `--version`, `--help`.

### Autenticación (opcional)

Para repositorios públicos no se necesita token. Para repositorios privados hace falta acceso autorizado. El programa lee, si existe, la variable de entorno `GITHUB_TOKEN`. **No crea, almacena ni imprime tokens**. Las redirecciones HTTP se bloquean por defecto, evitando reenviar `Authorization` a otros dominios. Evita incorporar tokens directamente a URLs o argumentos.

Un token válido con permisos de lectura adecuados puede permitir acceder al repositorio y a sus contenidos. Un `404` al consultar los metadatos puede significar repositorio inexistente **o sin permisos**. No pegues tokens ni secretos en un reporte ni los subas a GitHub.

## Auditorías

| Comprobación | Peso | Ausencia |
| --- | ---: | --- |
| README en raíz o docs | 15 | FAIL |
| Descripción | 5 | WARN |
| Licencia detectada | 10 | FAIL |
| SECURITY.md | 15 | WARN |
| CONTRIBUTING.md | 10 | WARN |
| CI detectada | 15 | WARN |
| Push en los últimos 180 días | 10 | WARN |
| No archivado | 10 | FAIL |
| Rama predeterminada | 5 | FAIL |
| Issues habilitados | 5 | WARN |

**Puntuación (0–100):** PASS recibe el peso completo, WARN recibe la mitad y FAIL recibe cero. UNKNOWN significa que la información no pudo consultarse y **se excluye del denominador**. Se normaliza la puntuación al peso efectivamente evaluado; si no se puede evaluar nada, la puntuación es `null` y se devuelve error de ejecución. El score es heurístico, no un escaneo de vulnerabilidades ni una garantía de seguridad.

Las políticas se buscan en raíz, `.github/` y `docs/`. Se detectan workflows YAML de GitHub Actions y archivos comunes de Travis, GitLab CI, Azure, Jenkins, CircleCI, Bitbucket y AppVeyor. No se comprueba la ejecución exitosa de pipelines; solamente su existencia.

### Códigos de salida

- **0**: auditoría realizada y umbral satisfecho (o no especificado).
- **1**: puntuación inferior a `--fail-under`.
- **2**: entrada inválida, problema de acceso, red o API, error de escritura, o puntuación no evaluable.

Si usas `--format json`, la salida estándar contiene solo JSON; diagnósticos van a stderr. El archivo `--output` se escribe de forma atómica; es una operación **local** autorizada, no una escritura en GitHub. El esquema del JSON indica `schema_version: 1` y contiene resultados y recomendaciones.

## Pruebas

```bash
python -m unittest discover -s tests -v
```

Las pruebas sustituyen las solicitudes HTTP por mocks y **no acceden a GitHub**.

## Estructura

```text
repohealthchecker/
  __init__.py       # Versión del paquete
  __main__.py       # python -m repohealthchecker
  cli.py            # Parser y códigos de salida
  github_client.py  # API GitHub GET + validación y errores
  checks.py         # Auditorías y puntuación
  models.py         # Modelo de resultados
  reporter.py       # Informe de texto y JSON + guardado atómico
  exceptions.py     # Excepciones controladas
tests/
  test_cli.py
  test_github_client.py
  test_checks.py
  test_reporter.py
pyproject.toml
README.md
.gitignore
LICENSE
```

## Limitaciones conocidas

- Un archivo de CI presente no implica que las pruebas estén pasando.
- La licencia es detectada por el campo `license` de GitHub o por nombre del archivo; no se valida jurídicamente.
- Los proyectos deliberadamente archivados, sin issues o sin contribuciones externas pueden recibir advertencias sin que ello represente un defecto real.
- Ante permisos insuficientes sobre archivos, estos indicadores quedan UNKNOWN. Si el acceso al repositorio está bloqueado, la auditoría devuelve error.
- El cliente reintenta hasta dos veces los fallos HTTP transitorios 500/502/503/504 con backoff corto; no ignora límites de tasa. Las redirecciones 3xx se rechazan por seguridad.
