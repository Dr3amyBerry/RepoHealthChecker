"""Interfaz CLI y códigos de salida predecibles."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from . import __version__
from .checks import audit_repository
from .exceptions import RepoHealthError
from .github_client import GitHubClient, parse_repository
from .reporter import render_json, render_text, write_report

EXIT_OK = 0
EXIT_SCORE_BELOW_THRESHOLD = 1
EXIT_ERROR = 2


def percentage(value: str) -> int:
    try:
        number = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("el umbral debe ser un entero entre 0 y 100") from error
    if not 0 <= number <= 100:
        raise argparse.ArgumentTypeError("el umbral debe estar entre 0 y 100")
    return number


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="repohealthchecker",
        description="Audita indicadores de salud de un repositorio GitHub (solo lectura).",
    )
    parser.add_argument("repository", help="owner/repo o https://github.com/owner/repo")
    parser.add_argument("--format", choices=("text", "json"), default="text",
                        help="Formato de salida (predeterminado: text).")
    parser.add_argument("--output", metavar="RUTA", help="Guarda el reporte en un archivo local.")
    parser.add_argument("--fail-under", type=percentage, metavar="0-100",
                        help="Devuelve código 1 si la puntuación es menor que el umbral.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        repo = parse_repository(args.repository)
        report = audit_repository(GitHubClient(), repo)
        rendered = render_json(report) if args.format == "json" else render_text(report)
        if args.output:
            write_report(args.output, rendered)
        else:
            print(rendered, end="")
        if report.score is None:
            print("Error: no se pudo evaluar ninguna verificación.", file=sys.stderr)
            return EXIT_ERROR
        if args.fail_under is not None and report.score < args.fail_under:
            return EXIT_SCORE_BELOW_THRESHOLD
        return EXIT_OK
    except (RepoHealthError, OSError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return EXIT_ERROR
