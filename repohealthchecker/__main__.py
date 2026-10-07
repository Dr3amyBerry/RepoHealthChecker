"""Permite ejecutar la herramienta mediante ``python -m repohealthchecker``."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
