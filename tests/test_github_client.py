"""Peticiones REST simuladas, parsing y seguridad de tokens."""

import io
import json
import socket
from urllib.request import Request
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from repohealthchecker.exceptions import (
    GitHubAPIError,
    GitHubAuthError,
    GitHubForbiddenError,
    GitHubNetworkError,
    GitHubNotFoundError,
    GitHubRateLimitError,
    GitHubResponseError,
    RepositoryValidationError,
)
from repohealthchecker.github_client import GitHubClient, _RejectRedirects, _safe_urlopen, parse_repository


class MockResponse:
    def __init__(self, data):
        self.data = data

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        if isinstance(self.data, bytes):
            return self.data
        return json.dumps(self.data).encode("utf-8")


def http_error(code, headers=None):
    return HTTPError("https://api.github.com/forbidden", code, "Test", headers or {}, io.BytesIO(b"{}"))


class ParseRepositoryTests(unittest.TestCase):
    def test_owner_repo(self):
        repo = parse_repository(" Rigor-Core/fudi ")
        self.assertEqual(repo.full_name, "Rigor-Core/fudi")

    def test_https_git_suffix(self):
        repo = parse_repository("https://github.com/org/repo.git/")
        self.assertEqual(repo.full_name, "org/repo")

    def test_invalid_repos(self):
        for value in (
            "", "repo", "/repo", "org/repo/extra", "org/..", "-owner/project",
            "org/in valid", "http://github.com/org/repo", "https://evil.com/org/repo",
            "https://github.com.evil.com/org/repo", "https://github.com/org/repo?token=123",
            "https://name:secret@github.com/org/repo", "https://github.com:443/org/repo",
            "https://github.com/org/repo#fragment", "org/repo%2Fextra",
        ):
            with self.subTest(value=value), self.assertRaises(RepositoryValidationError):
                parse_repository(value)


class GitHubClientTests(unittest.TestCase):
    def setUp(self):
        self.repo = parse_repository("acme/service")
        self.client = GitHubClient(token="fake-secret-token", max_retries=0)

    @patch("repohealthchecker.github_client._safe_urlopen")
    def test_get_repository_headers_and_read_only(self, urlopen):
        urlopen.return_value = MockResponse({"name": "service"})
        self.assertEqual(self.client.get_repository(self.repo)["name"], "service")
        request = urlopen.call_args.args[0]
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(request.full_url, "https://api.github.com/repos/acme/service")
        self.assertEqual(request.get_header("Authorization"), "Bearer fake-secret-token")
        self.assertNotIn("fake-secret-token", request.full_url)
        self.assertEqual(request.get_header("X-github-api-version"), "2022-11-28")

    @patch("repohealthchecker.github_client._safe_urlopen")
    def test_get_directory(self, urlopen):
        urlopen.return_value = MockResponse([{"name": "README.md", "type": "file"}])
        result = self.client.list_directory(self.repo, "docs")
        self.assertEqual(result[0]["name"], "README.md")
        self.assertTrue(urlopen.call_args.args[0].full_url.endswith("/contents/docs"))

    @patch("repohealthchecker.github_client._safe_urlopen")
    def test_directory_not_found_is_empty(self, urlopen):
        urlopen.side_effect = http_error(404)
        self.assertEqual(self.client.list_directory(self.repo, "missing"), [])

    @patch("repohealthchecker.github_client._safe_urlopen")
    def test_repository_not_found_is_error(self, urlopen):
        urlopen.side_effect = http_error(404)
        with self.assertRaises(GitHubNotFoundError):
            self.client.get_repository(self.repo)

    @patch("repohealthchecker.github_client._safe_urlopen")
    def test_errors_are_secret_free(self, urlopen):
        for status, error_type in (
            (401, GitHubAuthError), (403, GitHubForbiddenError),
            (429, GitHubRateLimitError), (502, GitHubAPIError),
        ):
            urlopen.side_effect = http_error(status)
            with self.subTest(status=status), self.assertRaises(error_type) as caught:
                self.client.get_repository(self.repo)
            self.assertNotIn("fake-secret-token", str(caught.exception))

    @patch("repohealthchecker.github_client._safe_urlopen")
    def test_rate_limit_403(self, urlopen):
        urlopen.side_effect = http_error(403, {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1234"})
        with self.assertRaises(GitHubRateLimitError) as caught:
            self.client.get_repository(self.repo)
        self.assertIn("1234", str(caught.exception))

    @patch("repohealthchecker.github_client._safe_urlopen")
    def test_secondary_rate_limit(self, urlopen):
        urlopen.side_effect = http_error(403, {"Retry-After": "60"})
        with self.assertRaises(GitHubRateLimitError):
            self.client.get_repository(self.repo)

    @patch("repohealthchecker.github_client.time.sleep")
    @patch("repohealthchecker.github_client._safe_urlopen")
    def test_retry_transient_error(self, urlopen, sleep):
        client = GitHubClient(token="x", max_retries=2)
        urlopen.side_effect = [http_error(502), http_error(503), MockResponse({"ok": True})]
        self.assertTrue(client.get_repository(self.repo)["ok"])
        self.assertEqual(urlopen.call_count, 3)
        self.assertEqual(sleep.call_count, 2)

    @patch("repohealthchecker.github_client._safe_urlopen")
    def test_network_errors(self, urlopen):
        for error in (URLError("offline"), socket.timeout("timeout"), TimeoutError("timeout")):
            urlopen.side_effect = error
            with self.subTest(error=error), self.assertRaises(GitHubNetworkError):
                self.client.get_repository(self.repo)

    @patch("repohealthchecker.github_client._safe_urlopen")
    def test_unexpected_json_and_shapes(self, urlopen):
        urlopen.return_value = MockResponse(b"invalid JSON")
        with self.assertRaises(GitHubResponseError):
            self.client.get_repository(self.repo)
        urlopen.return_value = MockResponse([1, 2, 3])
        with self.assertRaises(GitHubResponseError):
            self.client.get_repository(self.repo)
        urlopen.return_value = MockResponse({"type": "file"})
        with self.assertRaises(GitHubResponseError):
            self.client.list_directory(self.repo)


    @patch("repohealthchecker.github_client.build_opener")
    def test_no_redirect_handler_is_installed(self, build_opener):
        """La capa de transporte no debe usar el redirect handler por defecto."""
        request = Request(
            "https://api.github.com/repos/acme/service",
            headers={"Authorization": "Bearer fake-secret-token"},
            method="GET",
        )
        build_opener.return_value.open.return_value = MockResponse({"ok": True})
        with _safe_urlopen(request, timeout=10) as response:
            self.assertTrue(response.read())
        handler = build_opener.call_args.args[0]
        self.assertIsInstance(handler, _RejectRedirects)
        self.assertIsNone(handler.redirect_request(
            request, None, 302, "Redirect", {"Location": "https://evil.invalid/"},
            "https://evil.invalid/",
        ))
        forwarded_request = build_opener.return_value.open.call_args.args[0]
        self.assertEqual(forwarded_request.full_url, "https://api.github.com/repos/acme/service")

    @patch("repohealthchecker.github_client._safe_urlopen")
    def test_redirect_is_rejected_without_leaking_token(self, safe_open):
        safe_open.side_effect = http_error(302, {"Location": "https://evil.invalid/capture"})
        with self.assertRaises(GitHubResponseError) as caught:
            self.client.get_repository(self.repo)
        self.assertIn("redirección", str(caught.exception))
        self.assertNotIn("fake-secret-token", str(caught.exception))

    def test_client_config(self):
        with self.assertRaises(ValueError):
            GitHubClient(timeout=0)
        with self.assertRaises(ValueError):
            GitHubClient(max_retries=-1)

    @patch.dict("os.environ", {"GITHUB_TOKEN": "env-secret"})
    @patch("repohealthchecker.github_client._safe_urlopen")
    def test_optional_environment_token(self, urlopen):
        urlopen.return_value = MockResponse({"name": "service"})
        GitHubClient().get_repository(self.repo)
        self.assertEqual(urlopen.call_args.args[0].get_header("Authorization"), "Bearer env-secret")


if __name__ == "__main__":
    unittest.main()
