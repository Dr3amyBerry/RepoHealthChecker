"""Pruebas de CLI sin consultas de red."""

from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from repohealthchecker.cli import main
from repohealthchecker.exceptions import GitHubNotFoundError
from repohealthchecker.models import AuditReport, CheckResult, Status


REPORT = AuditReport(
    "org/project", "2026-10-06T00:00:00Z", 80, 100, 100,
    (CheckResult("readme", "README", "Docs", Status.PASS, 15, "ok"),),
)


class CliTests(unittest.TestCase):
    def run_cli(self, argv, report=REPORT):
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch("repohealthchecker.cli.audit_repository", return_value=report), \
             patch("repohealthchecker.cli.GitHubClient"), \
             redirect_stdout(stdout), redirect_stderr(stderr):
            return_code = main(argv)
        return return_code, stdout.getvalue(), stderr.getvalue()

    def test_text_success(self):
        code, stdout, stderr = self.run_cli(["org/project"])
        self.assertEqual((code, stderr), (0, ""))
        self.assertIn("80/100", stdout)

    def test_json_success_and_clean_stderr(self):
        code, stdout, stderr = self.run_cli(["org/project", "--format", "json"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout)["score"], 80)
        self.assertEqual(stderr, "")

    def test_threshold_pass_and_fail(self):
        self.assertEqual(self.run_cli(["org/project", "--fail-under", "80"])[0], 0)
        self.assertEqual(self.run_cli(["org/project", "--fail-under", "81"])[0], 1)

    def test_output_file(self):
        with TemporaryDirectory() as temp:
            filename = Path(temp) / "audit.json"
            code, stdout, _ = self.run_cli(["org/project", "--format", "json", "--output", str(filename)])
            self.assertEqual(code, 0)
            self.assertEqual(stdout, "")
            self.assertEqual(json.loads(filename.read_text(encoding="utf-8"))["score"], 80)

    def test_invalid_repository(self):
        code, stdout, stderr = self.run_cli(["bad//name"])
        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertIn("Error:", stderr)

    def test_gh_error_to_stderr(self):
        with patch("repohealthchecker.cli.GitHubClient"), \
             patch("repohealthchecker.cli.audit_repository", side_effect=GitHubNotFoundError("repo missing")):
            stdout, stderr = io.StringIO(), io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = main(["org/project", "--format", "json"])
        self.assertEqual(code, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("repo missing", stderr.getvalue())

    def test_not_evaluable_report(self):
        empty = AuditReport("org/project", "2026-10-06T00:00:00Z", None, 0, 100, tuple())
        code, stdout, stderr = self.run_cli(["org/project", "--format", "json"], report=empty)
        self.assertEqual(code, 2)
        self.assertIsNone(json.loads(stdout)["score"])
        self.assertIn("no se pudo evaluar", stderr)

    def test_invalid_threshold_is_usage_error(self):
        with redirect_stderr(io.StringIO()):
            for invalid in ("-1", "101", "2.5"):
                with self.subTest(value=invalid), self.assertRaises(SystemExit) as exit_code:
                    main(["org/project", "--fail-under", invalid])
                self.assertEqual(exit_code.exception.code, 2)

    def test_failed_file_write(self):
        with TemporaryDirectory() as temp:
            code, stdout, stderr = self.run_cli(["org/project", "--output", str(Path(temp) / "missing" / "r.txt")])
            self.assertEqual(code, 2)
            self.assertEqual(stdout, "")
            self.assertIn("Error:", stderr)


if __name__ == "__main__":
    unittest.main()
