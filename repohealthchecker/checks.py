"""Motor de auditoría con puntuación reproducible y ausencias no penalizadas."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from .exceptions import GitHubAPIError, GitHubAuthError, GitHubRateLimitError
from .github_client import GitHubClient, RepositoryRef
from .models import AuditReport, CheckResult, Status

# La suma de todos los pesos es 100. WARN concede la mitad; UNKNOWN no computa.
WEIGHTS: dict[str, int] = {
    "readme": 15,
    "description": 5,
    "license": 10,
    "security": 15,
    "contributing": 10,
    "ci": 15,
    "recent_activity": 10,
    "not_archived": 10,
    "default_branch": 5,
    "issues_enabled": 5,
}
STALE_AFTER_DAYS = 180

# None significa que la consulta falló: no equivale a un directorio vacío.
Entries = list[dict[str, Any]] | None


def _has_file(entries: Entries, candidates: Iterable[str]) -> bool | None:
    if entries is None:
        return None
    candidate_set = {candidate.lower() for candidate in candidates}
    return any(
        item["type"] == "file" and item["name"].lower() in candidate_set
        for item in entries
    )


def _has_prefix(entries: Entries, prefixes: tuple[str, ...]) -> bool | None:
    if entries is None:
        return None
    return any(
        item["type"] == "file"
        and any(
            item["name"].lower() == prefix
            or item["name"].lower().startswith(prefix + separator)
            for prefix in prefixes for separator in (".", "-", "_")
        )
        for item in entries
    )


def _has_yaml_workflow(entries: Entries) -> bool | None:
    if entries is None:
        return None
    return any(
        item["type"] == "file"
        and item["name"].lower().endswith((".yml", ".yaml"))
        for item in entries
    )


def _combine(*results: bool | None) -> bool | None:
    if True in results:
        return True
    if None in results:
        return None
    return False


def _get_child_directory(
    client: GitHubClient, repo: RepositoryRef,
    parent: Entries, child_name: str, full_path: str,
) -> Entries:
    if parent is None:
        return None
    if not any(item["type"] == "dir" and item["name"].lower() == child_name.lower()
               for item in parent):
        return []
    try:
        return client.list_directory(repo, full_path)
    except (GitHubAuthError, GitHubRateLimitError):
        raise
    except GitHubAPIError:
        return None


def _root(client: GitHubClient, repo: RepositoryRef) -> Entries:
    try:
        return client.list_directory(repo)
    except (GitHubAuthError, GitHubRateLimitError):
        raise
    except GitHubAPIError:
        return None


def _result(
    identifier: str, name: str, category: str, condition: bool | None,
    *, fail_when_missing: bool, passed: str, missing: str, recommendation: str,
) -> CheckResult:
    if condition is True:
        return CheckResult(identifier, name, category, Status.PASS, WEIGHTS[identifier], passed)
    if condition is None:
        return CheckResult(
            identifier, name, category, Status.UNKNOWN, WEIGHTS[identifier],
            "No se pudo comprobar este requisito con la información accesible.",
            "Vuelve a ejecutar la auditoría cuando la API esté disponible.",
        )
    return CheckResult(
        identifier, name, category,
        Status.FAIL if fail_when_missing else Status.WARN,
        WEIGHTS[identifier], missing, recommendation,
    )


def _metadata_bool(data: dict[str, Any], name: str) -> bool | None:
    value = data.get(name)
    return value if isinstance(value, bool) else None


def _recent_activity(metadata: dict[str, Any], now: datetime) -> CheckResult:
    raw = metadata.get("pushed_at")
    condition: bool | None = None
    age_days = None
    if raw is None and "pushed_at" in metadata:
        condition = False
    elif isinstance(raw, str):
        try:
            timestamp = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if timestamp.tzinfo is not None:
                age = now - timestamp.astimezone(timezone.utc)
                if age >= timedelta(days=-1):
                    age_days = max(0, age.days)
                    condition = age <= timedelta(days=STALE_AFTER_DAYS)
        except ValueError:
            pass
    if condition is True:
        explanation = f"Último push hace {age_days} días (umbral: {STALE_AFTER_DAYS})."
    elif condition is False:
        explanation = ("No hay pushes registrados." if raw is None else
                       f"Último push hace {age_days} días (umbral: {STALE_AFTER_DAYS}).")
    else:
        explanation = "La fecha del último push no está disponible o no es válida."
    return CheckResult(
        "recent_activity", "Actividad reciente", "Mantenimiento",
        Status.PASS if condition is True else Status.WARN if condition is False else Status.UNKNOWN,
        WEIGHTS["recent_activity"], explanation,
        "Revisa la actividad de mantenimiento si el proyecto sigue activo." if condition is False else None,
    )


def calculate_score(checks: Iterable[CheckResult]) -> tuple[int | None, int]:
    """Normaliza a 0-100 excluyendo UNKNOWN del denominador."""
    evaluated = [check for check in checks if check.status != Status.UNKNOWN]
    weight = sum(check.weight for check in evaluated)
    if weight == 0:
        return None, 0
    earned_twice = sum(
        check.weight * (2 if check.status == Status.PASS else 1 if check.status == Status.WARN else 0)
        for check in evaluated
    )
    return round(earned_twice * 50 / weight), weight


def audit_repository(
    client: GitHubClient, repo: RepositoryRef, now: datetime | None = None,
) -> AuditReport:
    """Audita solo datos visibles. Errores parciales se representan como UNKNOWN."""
    metadata = client.get_repository(repo)
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("now debe tener zona horaria")
    current = current.astimezone(timezone.utc)

    root = _root(client, repo)
    github = _get_child_directory(client, repo, root, ".github", ".github")
    docs = _get_child_directory(client, repo, root, "docs", "docs")
    workflows = _get_child_directory(client, repo, github, "workflows", ".github/workflows")
    circleci = _get_child_directory(client, repo, root, ".circleci", ".circleci")

    readme_names = (
        "readme", "readme.md", "readme.rst", "readme.txt", "readme.markdown",
        "readme.adoc", "readme.mdown",
    )
    readme = _combine(_has_file(root, readme_names), _has_file(docs, readme_names))
    license_detected = _combine(
        True if metadata.get("license") else False,
        _has_prefix(root, ("license", "licence", "copying", "unlicense")),
    )
    security = _combine(*(
        _has_file(entries, ("security.md", "security.txt", "security.rst"))
        for entries in (root, github, docs)
    ))
    contributing = _combine(*(
        _has_file(entries, ("contributing.md", "contributing.rst", "contributing.txt"))
        for entries in (root, github, docs)
    ))
    ci = _combine(
        _has_yaml_workflow(workflows),
        _has_file(root, (
            ".travis.yml", ".gitlab-ci.yml", "azure-pipelines.yml", "jenkinsfile",
            "bitbucket-pipelines.yml", "appveyor.yml",
        )),
        _has_file(circleci, ("config.yml", "config.yaml")),
    )

    description: bool | None = None
    if "description" in metadata:
        description = bool(metadata["description"] and str(metadata["description"]).strip())
    branch: bool | None = None
    if "default_branch" in metadata:
        branch = bool(isinstance(metadata["default_branch"], str)
                      and metadata["default_branch"].strip())

    results = [
        _result("readme", "README", "Documentación", readme,
                fail_when_missing=True,
                passed="Se encontró documentación README.",
                missing="No se encontró un README reconocido en raíz o docs/.",
                recommendation="Añade README.md con instalación, uso y objetivos."),
        _result("description", "Descripción", "Documentación", description,
                fail_when_missing=False,
                passed="El repositorio tiene descripción.",
                missing="No se configuró una descripción del repositorio.",
                recommendation="Agrega una descripción breve en GitHub."),
        _result("license", "Licencia", "Licencias", license_detected,
                fail_when_missing=True,
                passed="Se detectó una licencia reconocida o archivo de licencia.",
                missing="No se detectó licencia en los metadatos ni en la raíz.",
                recommendation="Elige y documenta una licencia adecuada."),
        _result("security", "Política de seguridad", "Seguridad", security,
                fail_when_missing=False,
                passed="Se encontró SECURITY.md o equivalente.",
                missing="No se encontró política de divulgación de vulnerabilidades.",
                recommendation="Añade SECURITY.md con instrucciones de reporte."),
        _result("contributing", "Guía de contribución", "Colaboración", contributing,
                fail_when_missing=False,
                passed="Se encontró CONTRIBUTING.md o equivalente.",
                missing="No se encontró guía de contribución.",
                recommendation="Añade CONTRIBUTING.md si aceptas contribuciones."),
        _result("ci", "Integración continua", "Automatización", ci,
                fail_when_missing=False,
                passed="Se detectó una configuración de integración continua.",
                missing="No se detectó configuración de CI entre las compatibles.",
                recommendation="Configura GitHub Actions u otro sistema de CI compatible."),
        _recent_activity(metadata, current),
        _result("not_archived", "Repositorio activo", "Mantenimiento",
                None if _metadata_bool(metadata, "archived") is None
                else not _metadata_bool(metadata, "archived"),
                fail_when_missing=True,
                passed="El repositorio no está archivado.",
                missing="El repositorio está archivado.",
                recommendation="Verifica si debe seguir archivado; puede ser intencional."),
        _result("default_branch", "Rama predeterminada", "Metadatos", branch,
                fail_when_missing=True,
                passed="Existe una rama predeterminada configurada.",
                missing="No se encontró rama predeterminada.",
                recommendation="Configura la rama predeterminada del repositorio."),
        _result("issues_enabled", "Seguimiento de incidencias", "Colaboración",
                _metadata_bool(metadata, "has_issues"),
                fail_when_missing=False,
                passed="El sistema de issues está habilitado.",
                missing="Issues está deshabilitado (puede ser una decisión intencional).",
                recommendation="Habilita issues si quieres recibir incidencias en GitHub."),
    ]
    score, evaluated_weight = calculate_score(results)
    return AuditReport(
        repository=repo.full_name,
        generated_at=current.isoformat().replace("+00:00", "Z"),
        score=score,
        evaluated_weight=evaluated_weight,
        total_weight=sum(WEIGHTS.values()),
        checks=tuple(results),
    )
