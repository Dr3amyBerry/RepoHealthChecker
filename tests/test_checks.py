"""Pruebas de scoring, evidencia parcial, detección de archivos y fecha."""

from datetime import datetime, timezone
import unittest

from repohealthchecker.checks import WEIGHTS, audit_repository, calculate_score
from repohealthchecker.exceptions import GitHubForbiddenError, GitHubNotFoundError, GitHubRateLimitError
from repohealthchecker.github_client import parse_repository
from repohealthchecker.models import CheckResult, Status

FIXED_NOW = datetime(2026, 10, 6, tzinfo=timezone.utc)


def files(*names):
    return [{"name": name, "type": "file"} for name in names]


def dirs(*names):
    return [{"name": name, "type": "dir"} for name in names]


class FakeClient:
    def __init__(self, metadata=None, content=None, errors=None):
        self.metadata = metadata or {
            "description": "Servicio de prueba",
            "license": {"spdx_id": "MIT"},
            "pushed_at": "2026-10-01T00:00:00Z",
            "archived": False,
            "default_branch": "main",
            "has_issues": True,
        }
        self.content = content if content is not None else {
            "": files("README.md", "LICENSE") + dirs(".github", "docs", ".circleci"),
            ".github": files("SECURITY.md", "CONTRIBUTING.md") + dirs("workflows"),
            "docs": [],
            ".github/workflows": files("ci.yml"),
            ".circleci": files("config.yml"),
        }
        self.errors = errors or {}
        self.called = []

    def get_repository(self, _repo):
        return self.metadata

    def list_directory(self, _repo, path=""):
        self.called.append(path)
        if path in self.errors:
            raise self.errors[path]
        return self.content.get(path, [])


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.repo = parse_repository("org/project")

    def test_weights_total_100(self):
        self.assertEqual(sum(WEIGHTS.values()), 100)

    def test_all_pass(self):
        report = audit_repository(FakeClient(), self.repo, FIXED_NOW)
        self.assertEqual(report.score, 100)
        self.assertEqual(report.evaluated_weight, 100)
        self.assertTrue(all(check.status == Status.PASS for check in report.checks))
        self.assertEqual(report.to_dict()["summary"]["PASS"], 10)

    def test_empty_repository(self):
        metadata = {
            "description": None, "license": None, "pushed_at": None,
            "archived": True, "default_branch": None, "has_issues": False,
        }
        report = audit_repository(FakeClient(metadata=metadata, content={"": []}), self.repo, FIXED_NOW)
        self.assertEqual(report.score, 30)
        self.assertEqual(report.evaluated_weight, 100)
        self.assertEqual(len(report.checks), 10)
        self.assertEqual(report.to_dict()["summary"], {"PASS": 0, "WARN": 6, "FAIL": 4, "UNKNOWN": 0})

    def test_similar_but_invalid_document_names_do_not_count(self):
        metadata = FakeClient().metadata.copy()
        metadata["license"] = None
        report = audit_repository(FakeClient(metadata=metadata, content={
            "": files("README.exe", "licenseplate.png")
        }), self.repo, FIXED_NOW)
        self.assertEqual(report.checks[0].status, Status.FAIL)
        self.assertEqual(report.checks[2].status, Status.FAIL)

    def test_non_visible_directory_is_unknown(self):
        content = {"": files("README.md") + dirs(".github"), ".github": dirs("workflows")}
        client = FakeClient(content=content, errors={".github": GitHubForbiddenError("blocked")})
        report = audit_repository(client, self.repo, FIXED_NOW)
        by_id = {item.identifier: item for item in report.checks}
        self.assertEqual(by_id["security"].status, Status.UNKNOWN)
        self.assertEqual(by_id["contributing"].status, Status.UNKNOWN)
        self.assertEqual(by_id["ci"].status, Status.UNKNOWN)
        self.assertEqual(report.evaluated_weight, 60)
        self.assertGreater(report.score, 0)

    def test_root_error_marks_content_checks_unknown(self):
        client = FakeClient(errors={"": GitHubForbiddenError("blocked")})
        report = audit_repository(client, self.repo, FIXED_NOW)
        for item in report.checks:
            if item.identifier in ("readme", "security", "contributing", "ci"):
                self.assertEqual(item.status, Status.UNKNOWN)
        # Se siguen evaluando metadatos; no se atribuyen ausencias imaginarias.
        self.assertEqual(report.evaluated_weight, 45)

    def test_rate_limit_propagates(self):
        with self.assertRaises(GitHubRateLimitError):
            audit_repository(FakeClient(errors={"": GitHubRateLimitError("limit")}), self.repo, FIXED_NOW)

    def test_recognized_alternative_ci(self):
        report = audit_repository(FakeClient(content={
            "": files("README.md", ".gitlab-ci.yml", "LICENCE.txt", "SECURITY.md", "CONTRIBUTING.md")
        }), self.repo, FIXED_NOW)
        by_id = {item.identifier: item for item in report.checks}
        self.assertEqual(by_id["ci"].status, Status.PASS)
        self.assertEqual(by_id["license"].status, Status.PASS)

    def test_readme_from_docs(self):
        report = audit_repository(FakeClient(content={
            "": dirs("docs"), "docs": files("README.rst")
        }), self.repo, FIXED_NOW)
        self.assertEqual(report.checks[0].status, Status.PASS)

    def test_stale_and_invalid_dates(self):
        for pushed_at, expected in (
            ("2020-01-01T00:00:00Z", Status.WARN),
            ("not-a-date", Status.UNKNOWN),
            ("2030-01-01T00:00:00Z", Status.UNKNOWN),
        ):
            metadata = FakeClient().metadata.copy()
            metadata["pushed_at"] = pushed_at
            with self.subTest(pushed_at=pushed_at):
                report = audit_repository(FakeClient(metadata=metadata), self.repo, FIXED_NOW)
                self.assertEqual(report.checks[6].status, expected)

    def test_unknown_score_no_denominator(self):
        checks = (
            CheckResult("a", "A", "X", Status.UNKNOWN, 80, "unknown"),
            CheckResult("b", "B", "X", Status.WARN, 20, "warn"),
        )
        self.assertEqual(calculate_score(checks), (50, 20))
        self.assertEqual(calculate_score(checks[:1]), (None, 0))

    def test_metadata_missing_is_unknown(self):
        report = audit_repository(FakeClient(metadata={"license": False}), self.repo, FIXED_NOW)
        self.assertEqual(report.checks[1].status, Status.UNKNOWN)
        self.assertEqual(report.checks[7].status, Status.UNKNOWN)
        self.assertEqual(report.checks[8].status, Status.UNKNOWN)
        self.assertEqual(report.checks[9].status, Status.UNKNOWN)

    def test_no_unnecessary_directory_api_requests(self):
        client = FakeClient(content={"": files("README.md")})
        audit_repository(client, self.repo, FIXED_NOW)
        self.assertEqual(client.called, [""])

    def test_utc_required(self):
        with self.assertRaises(ValueError):
            audit_repository(FakeClient(), self.repo, datetime(2026, 10, 6))


if __name__ == "__main__":
    unittest.main()
