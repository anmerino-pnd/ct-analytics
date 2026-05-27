"""
CLI del pipeline.

Uso:
    python -m pulse.pipeline daily
    python -m pulse.pipeline weekly
    python -m pulse.pipeline monthly

Opciones:
    --skip-ingest    Saltar el paso de extracción desde Mongo.
    --log-file PATH  Escribir logs a archivo (además de stdout).
    --verbose        Logging en nivel DEBUG.

Exit codes:
    0 = pipeline exitoso
    1 = quality check falló o error inesperado
    2 = error de argumentos
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from pulse.pipeline.runner import run


def _configurar_logging(log_file: Path | None, verbose: bool) -> None:
    """Configura logging a stdout (y opcionalmente a archivo)."""
    nivel = logging.DEBUG if verbose else logging.INFO
    formato = "%(asctime)s %(levelname)s %(name)s: %(message)s"

    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))

    logging.basicConfig(level=nivel, format=formato, handlers=handlers, force=True)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="pulse.pipeline",
        description="Pipeline de segmentación de clientes y MBA.",
    )
    parser.add_argument(
        "modo",
        choices=["daily", "weekly", "monthly"],
        help="Modo de ejecución del pipeline.",
    )
    parser.add_argument(
        "--skip-ingest",
        action="store_true",
        help="Saltar el paso de extracción desde Mongo (útil para re-procesar).",
    )
    parser.add_argument(
        "--log-file",
        type=Path,
        default=None,
        help="Ruta a archivo de log (además de stdout).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Logging en nivel DEBUG.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    _configurar_logging(args.log_file, args.verbose)

    resultado = run(modo=args.modo, skip_ingest=args.skip_ingest)
    return 0 if resultado.exitoso else 1


if __name__ == "__main__":
    sys.exit(main())