"""Cliente GitHub REST de solo lectura utilizando la biblioteca estándar."""

from __future__ import annotations

import json
import os
import re
import socket
import time
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .exceptions import (
    GitHubAPIError,
    GitHubAuthError,
    GitHubForbiddenError,
    GitHubNetworkError,
    GitHubNotFoundError,
    GitHubRateLimitError,
    GitHubResponseError,
    RepositoryValidationError,
)

OWNER_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?\Z")
REPO_RE = re.compile(r"[A-Za-z0-9_.-]{1,100}\Z")
RETRYABLE_CODES = frozenset({500, 502, 503, 504})
API_BASE = "https://api.github.com"


class _RejectRedirects(HTTPRedirectHandler):
    """Impide reenviar Authorization a un destino de redirección."""

    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def _safe_urlopen(request: Request, *, timeout: float):
    """Abre exclusivamente la URL original sin seguir redirecciones HTTP."""
    return build_opener(_RejectRedirects()).open(request, timeout=timeout)


@dataclass(frozen=True)
class RepositoryRef:
    owner: str
    name: str

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.name}"

    @property
    def api_path(self) -> str:
        return f"repos/{quote(self.owner, safe='')}/{quote(self.name, safe='')}"


def parse_repository(value: str) -> RepositoryRef:
    """Acepta ``owner/repo`` o ``https://github.com/owner/repo[.git]``."""
    raw = value.strip()
    if raw.startswith("https://") or "://" in raw:
        try:
            parsed = urlsplit(raw)
            valid_host = parsed.hostname is not None and parsed.hostname.lower() == "github.com"
            valid_port = parsed.port is None
        except ValueError as error:
            raise RepositoryValidationError("URL de repositorio inválida.") from error
        if (parsed.scheme != "https" or not valid_host or not valid_port
                or parsed.username is not None or parsed.password is not None
                or parsed.query or parsed.fragment):
            raise RepositoryValidationError("Utiliza una URL HTTPS de github.com sin parámetros.")
        raw = parsed.path.strip("/")
    parts = raw.split("/")
    if len(parts) != 2:
        raise RepositoryValidationError("Indica el repositorio como owner/repo o su URL HTTPS de GitHub.")
    owner, repo = parts
    if repo.endswith(".git"):
        repo = repo[:-4]
    if not OWNER_RE.fullmatch(owner) or not REPO_RE.fullmatch(repo) or repo in (".", ".."):
        raise RepositoryValidationError("El identificador owner/repo contiene caracteres no válidos.")
    return RepositoryRef(owner, repo)


class GitHubClient:
    """Solo realiza peticiones GET; nunca muta recursos remotos."""

    def __init__(self, token: str | None = None, timeout: float = 10.0, max_retries: int = 2):
        if timeout <= 0:
            raise ValueError("timeout debe ser positivo")
        if max_retries < 0:
            raise ValueError("max_retries no puede ser negativo")
        self._token = token if token is not None else os.environ.get("GITHUB_TOKEN")
        self.timeout = timeout
        self.max_retries = max_retries

    def _request_json(self, path: str) -> Any:
        url = f"{API_BASE}/{path.lstrip('/')}"
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "RepoHealthChecker/1.0",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        request = Request(url, headers=headers, method="GET")

        for attempt in range(self.max_retries + 1):
            try:
                with _safe_urlopen(request, timeout=self.timeout) as response:
                    raw = response.read()
                try:
                    return json.loads(raw)
                except (UnicodeDecodeError, json.JSONDecodeError) as error:
                    raise GitHubResponseError("GitHub devolvió JSON ilegible.") from error
            except HTTPError as error:
                status = error.code
                if status in RETRYABLE_CODES and attempt < self.max_retries:
                    time.sleep(0.25 * (2 ** attempt))
                    continue
                if 300 <= status < 400:
                    raise GitHubResponseError(
                        "GitHub respondió con una redirección que se rechazó por seguridad."
                    ) from None
                if status == 404:
                    raise GitHubNotFoundError("Recurso inexistente o no visible en GitHub (404).") from None
                if status == 401:
                    raise GitHubAuthError("Autenticación rechazada por GitHub (401).") from None
                remaining = error.headers.get("X-RateLimit-Remaining") if error.headers else None
                retry_after = error.headers.get("Retry-After") if error.headers else None
                if status == 429 or (status == 403 and (remaining == "0" or retry_after)):
                    reset = error.headers.get("X-RateLimit-Reset") if error.headers else None
                    detail = f" Se podrá reintentar tras el instante Unix {reset}." if reset and reset.isdigit() else ""
                    raise GitHubRateLimitError("Límite de la API de GitHub alcanzado." + detail) from None
                if status == 403:
                    raise GitHubForbiddenError("GitHub denegó el acceso a un recurso (403).") from None
                raise GitHubAPIError(f"GitHub respondió con HTTP {status}.") from None
            except (URLError, socket.timeout, TimeoutError, ConnectionError) as error:
                raise GitHubNetworkError("No fue posible conectar con la API de GitHub.") from error
        raise GitHubAPIError("No fue posible completar la consulta a GitHub.")

    def get_repository(self, repo: RepositoryRef) -> dict[str, Any]:
        data = self._request_json(repo.api_path)
        if not isinstance(data, dict):
            raise GitHubResponseError("La API devolvió metadatos de repositorio inesperados.")
        return data

    def list_directory(self, repo: RepositoryRef, directory: str = "") -> list[dict[str, Any]]:
        """Lista contenido; 404 en Contents API equivale a ruta inexistente."""
        safe_segments = [quote(part, safe="") for part in directory.split("/") if part]
        path = f"{repo.api_path}/contents"
        if safe_segments:
            path += "/" + "/".join(safe_segments)
        try:
            data = self._request_json(path)
        except GitHubNotFoundError:
            return []
        if not isinstance(data, list) or not all(
            isinstance(item, dict)
            and isinstance(item.get("name"), str)
            and item.get("type") in ("file", "dir", "symlink", "submodule")
            for item in data
        ):
            raise GitHubResponseError("GitHub devolvió una lista de archivos inesperada.")
        return data
