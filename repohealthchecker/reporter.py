"""Presentación de informes en texto legible o JSON versionado."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from .models import AuditReport


def render_json(report: AuditReport) -> str:
    return json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n"


def render_text(report: AuditReport) -> str:
    score = f"{report.score}/100" if report.score is not None else "N/D"
    lines = [
        "RepoHealthChecker — Informe de auditoría",
        f"Repositorio: {report.repository}",
        f"Fecha (UTC): {report.generated_at}",
        f"Puntuación: {score} (peso evaluado: {report.evaluated_weight}/{report.total_weight})",
        "Nota: WARN obtiene medio peso; UNKNOWN no afecta la puntuación.",
        "",
    ]
    for item in report.checks:
        lines.append(f"[{item.status.value:7}] {item.name} [{item.weight} pts] — {item.explanation}")
        if item.recommendation:
            lines.append(f"          Sugerencia: {item.recommendation}")
    summary = report.to_dict()["summary"]
    lines.extend([
        "",
        "Resumen: " + ", ".join(f"{name}={count}" for name, count in summary.items()),
        "Advertencia: esta auditoría verifica indicadores públicos, no vulnerabilidades de código.",
    ])
    return "\n".join(lines) + "\n"


def write_report(destination: str | Path, content: str) -> None:
    """Escritura atómica: evita truncar informes existentes ante fallos parciales."""
    path = Path(destination)
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n",
            dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False,
        ) as stream:
            temporary = stream.name
            stream.write(content)
        os.replace(temporary, path)
    finally:
        if temporary is not None and os.path.exists(temporary):
            os.unlink(temporary)
