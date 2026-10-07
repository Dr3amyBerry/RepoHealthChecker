"""Formato y guardado de los reportes."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from repohealthchecker.models import AuditReport, CheckResult, Status
from repohealthchecker.reporter import render_json, render_text, write_report


class ReporterTests(unittest.TestCase):
    def setUp(self):
        self.report = AuditReport(
            "acme/demo", "2026-10-06T00:00:00Z", 50, 20, 100,
            (CheckResult("readme", "README", "Documentación", Status.WARN, 20,
                         "No está", "Añádelo"),),
        )

    def test_json_schema(self):
        document = json.loads(render_json(self.report))
        self.assertEqual(document["schema_version"], 1)
        self.assertEqual(document["repository"], "acme/demo")
        self.assertEqual(document["checks"][0]["status"], "WARN")
        self.assertEqual(document["summary"], {"PASS": 0, "WARN": 1, "FAIL": 0, "UNKNOWN": 0})

    def test_text(self):
        text = render_text(self.report)
        self.assertIn("Puntuación: 50/100", text)
        self.assertIn("Sugerencia: Añádelo", text)
        self.assertIn("UNKNOWN no afecta", text)

    def test_none_score(self):
        report = AuditReport("x/y", "2026-10-06T00:00:00Z", None, 0, 100, tuple())
        self.assertIn("Puntuación: N/D", render_text(report))
        self.assertIsNone(json.loads(render_json(report))["score"])

    def test_atomic_file_save(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / "resultado.json"
            path.write_text("old", encoding="utf-8")
            write_report(path, "nuevo\n")
            self.assertEqual(path.read_text(encoding="utf-8"), "nuevo\n")
            self.assertEqual(list(Path(temp).iterdir()), [path])

    def test_invalid_directory(self):
        with TemporaryDirectory() as temp:
            with self.assertRaises(OSError):
                write_report(Path(temp) / "missing" / "report.txt", "hello")


if __name__ == "__main__":
    unittest.main()
