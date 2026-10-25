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

from .converter import ConversionError, ConversionRequest, convert_image, convert_request
from .documents.pdf_workbench import (
    extract_pdf_pages,
    merge_pdfs,
    reorder_pdf_pages,
    rotate_pdf_pages,
    split_pdf,
)
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
        help="Convert a file to a different format.",
        description="Convert a document or image to a different format.",
    )
    p.add_argument("input", type=Path, help="Path to the input file.")
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

    # PDF Workbench Subcommands
    p_pdf = sub.add_parser(
        "pdf",
        help="PDF workbench operations.",
        description="Merge, split, extract, reorder, or rotate PDF documents.",
    )
    pdf_sub = p_pdf.add_subparsers(dest="pdf_cmd", required=True)

    # pdf merge
    p_merge = pdf_sub.add_parser("merge", help="Merge multiple PDFs in order.")
    p_merge.add_argument("inputs", nargs="+", type=Path, help="Input PDF files.")
    p_merge.add_argument("-o", "--output", type=Path, help="Output PDF path.")
    p_merge.add_argument("--output-dir", type=Path, help="Output directory.")

    # pdf split
    p_split = pdf_sub.add_parser("split", help="Split a PDF into separate pages.")
    p_split.add_argument("input", type=Path, help="Input PDF file.")
    p_split.add_argument("--pages", default="all", help="Pages to split (e.g. 'all', '1-3', '1, 3').")
    p_split.add_argument("--output-dir", type=Path, help="Output directory.")
    p_split.add_argument("--pattern", help="Filename pattern, e.g. '{stem}_page_{page}.pdf'.")

    # pdf extract
    p_extract = pdf_sub.add_parser("extract", help="Extract pages to a single new PDF.")
    p_extract.add_argument("input", type=Path, help="Input PDF file.")
    p_extract.add_argument("--pages", required=True, help="Pages to extract (e.g. '1-3, 5').")
    p_extract.add_argument("-o", "--output", type=Path, help="Output PDF path.")
    p_extract.add_argument("--output-dir", type=Path, help="Output directory.")

    # pdf reorder
    p_reorder = pdf_sub.add_parser("reorder", help="Reorder pages in a PDF.")
    p_reorder.add_argument("input", type=Path, help="Input PDF file.")
    p_reorder.add_argument("--order", required=True, help="Page sequence (e.g. '3, 1, 2').")
    p_reorder.add_argument("-o", "--output", type=Path, help="Output PDF path.")
    p_reorder.add_argument("--output-dir", type=Path, help="Output directory.")

    # pdf rotate
    p_rotate = pdf_sub.add_parser("rotate", help="Rotate pages in a PDF.")
    p_rotate.add_argument("input", type=Path, help="Input PDF file.")
    p_rotate.add_argument("--angle", required=True, type=int, help="Rotation angle (90, 180, 270).")
    p_rotate.add_argument("--pages", default="all", help="Pages to rotate.")
    p_rotate.add_argument("-o", "--output", type=Path, help="Output PDF path.")
    p_rotate.add_argument("--output-dir", type=Path, help="Output directory.")

    return parser


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(errors="backslashreplace")
        except Exception:
            pass
    if hasattr(sys.stderr, "reconfigure"):
        try:
            sys.stderr.reconfigure(errors="backslashreplace")
        except Exception:
            pass

    parser = _build_parser()
    args = parser.parse_args()

    level = logging.DEBUG if args.verbose else logging.WARNING
    logging.basicConfig(stream=sys.stderr, level=level,
                        format="%(levelname)s %(name)s: %(message)s")

    try:
        if args.cmd == "convert":
            req = ConversionRequest(
                source=args.input,
                target_format=args.to,
                output_dir=args.output_dir,
            )
            res = convert_request(req)
            if res.output_paths and len(res.output_paths) > 1:
                for p in res.output_paths:
                    print(f"Saved: {p}")
            else:
                print(f"Saved: {res.output_path}")

        elif args.cmd == "pdf":
            if args.pdf_cmd == "merge":
                out = merge_pdfs(args.inputs, output_path=args.output, output_dir=args.output_dir)
                print(f"Saved: {out}")
            elif args.pdf_cmd == "split":
                outs = split_pdf(args.input, output_dir=args.output_dir, pages=args.pages, output_pattern=args.pattern)
                for p in outs:
                    print(f"Saved: {p}")
            elif args.pdf_cmd == "extract":
                out = extract_pdf_pages(args.input, pages=args.pages, output_path=args.output, output_dir=args.output_dir)
                print(f"Saved: {out}")
            elif args.pdf_cmd == "reorder":
                order = [int(x.strip()) for x in args.order.split(",") if x.strip()]
                out = reorder_pdf_pages(args.input, page_order=order, output_path=args.output, output_dir=args.output_dir)
                print(f"Saved: {out}")
            elif args.pdf_cmd == "rotate":
                out = rotate_pdf_pages(args.input, rotation=args.angle, pages=args.pages, output_path=args.output, output_dir=args.output_dir)
                print(f"Saved: {out}")
    except ConversionError as exc:
        parser.exit(2, f"Operation failed: {exc}\n")
    except KeyboardInterrupt:
        parser.exit(130, "\nInterrupted.\n")


if __name__ == "__main__":
    main()
