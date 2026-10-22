"""
localshift.cli — Command-line interface.

Provides the ``localshift convert`` subcommand.

Usage
-----
    localshift convert <input> --to <format> [--output-dir <dir>]

Both canonical format keys (``jpeg``) and common aliases (``jpg``) are accepted
for ``--to``.  The available choices are printed in the help text.

This module depends only on the backend (``converter``, ``formats``).
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .converter import ConversionError, convert_image
from .formats import ALIASES, SUPPORTED

log = logging.getLogger(__name__)

# All format strings a user may reasonably supply (canonical + aliases).
_ALL_FORMAT_CHOICES: list[str] = sorted(SUPPORTED | set(ALIASES.keys()))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="localshift",
        description="LocalShift — offline, privacy-first file converter.",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable debug logging to stderr.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser(
        "convert",
        help="Convert an image file.",
        description="Convert a raster image to a different format.",
    )
    p.add_argument("input", type=Path, help="Path to the input image.")
    p.add_argument(
        "--to",
        required=True,
        choices=_ALL_FORMAT_CHOICES,
        metavar="FORMAT",
        help=(
            f"Target format. Accepted values: {', '.join(_ALL_FORMAT_CHOICES)}."
        ),
    )
    p.add_argument(
        "--output-dir",
        type=Path,
        metavar="DIR",
        help="Directory for the output file. Defaults to the same folder as the input.",
    )
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    level = logging.DEBUG if args.verbose else logging.WARNING
    logging.basicConfig(stream=sys.stderr, level=level,
                        format="%(levelname)s %(name)s: %(message)s")

    try:
        output = convert_image(args.input, args.to, args.output_dir)
        print(f"Saved: {output}")
    except ConversionError as exc:
        parser.exit(2, f"Conversion failed: {exc}\n")
    except KeyboardInterrupt:
        parser.exit(130, "\nInterrupted.\n")


if __name__ == "__main__":
    main()
