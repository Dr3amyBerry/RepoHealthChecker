"""Errores públicos sin contenido de tokens ni cabeceras HTTP sensibles."""


class RepoHealthError(Exception):
    """Error controlado de ejecución."""


class RepositoryValidationError(RepoHealthError):
    """Identificador o URL de repositorio no válido."""


class GitHubAPIError(RepoHealthError):
    """Error al consultar la API de GitHub."""


class GitHubNotFoundError(GitHubAPIError):
    """Recurso no encontrado o no visible con los permisos actuales."""


class GitHubAuthError(GitHubAPIError):
    """Token de acceso inválido o revocado."""


class GitHubForbiddenError(GitHubAPIError):
    """Acceso denegado a un recurso de GitHub."""


class GitHubRateLimitError(GitHubAPIError):
    """Límite de peticiones de GitHub alcanzado."""


class GitHubNetworkError(GitHubAPIError):
    """Problema de conexión o tiempo de espera."""


class GitHubResponseError(GitHubAPIError):
    """Respuesta de GitHub inesperada o ilegible."""
