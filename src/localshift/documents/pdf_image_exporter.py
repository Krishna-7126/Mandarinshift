"""
localshift.documents.pdf_image_exporter — Offline PDF to PNG/JPEG raster export engine.

Provides bounded, resource-aware rasterization of PDF pages to PNG or JPEG images with:
- Safe structural inspection (validates encryption, corruption, page limits, dimensions).
- Strict page selection parsing (all, single page, ranges, comma lists).
- Configurable DPI (72-400), JPEG quality (1-100), and custom background fill.
- Flexible output naming patterns with token substitution ({stem}, {page}, {page_count}, {ext}).
- Collision-free in-process reservations and atomic file replacement per page.
- Cooperative cancellation and complete cleanup on failure.
"""
from __future__ import annotations

import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

from PIL import Image
import pypdfium2

from ..exceptions import (
    ConversionCancelledError,
    ConversionFailedError,
    InputTooLargeError,
    InvalidInputError,
)
from .pdf_inspector import PdfInspector
from .renderer import PdfPageRenderer

log = logging.getLogger(__name__)

# Maximum pages supported in a single document conversion
MAX_PAGES_LIMIT: int = 2000


class PdfToImageExporter:
    """PDF page rasterization and image export engine."""

    @classmethod
    def parse_page_selection(cls, pages_spec: Any, total_pages: int) -> list[int]:
        """Parse and validate page selection specification into 1-based page numbers.

        Parameters
        ----------
        pages_spec:
            'all', empty string, integer, or comma-separated tokens/ranges
            (e.g., '1', '1-3', '1, 3, 5').
        total_pages:
            Total number of pages in the PDF document.

        Returns
        -------
        list[int]
            List of 1-based page numbers in requested order without duplicates.
        """
        if total_pages < 1:
            raise InvalidInputError("PDF document contains 0 pages.")

        if pages_spec is None or pages_spec == "" or pages_spec == "all":
            return tuple(range(1, total_pages + 1))

        if isinstance(pages_spec, int):
            if pages_spec < 1 or pages_spec > total_pages:
                raise InvalidInputError(
                    f"Selected page {pages_spec} is out of bounds (document has {total_pages} pages). Page number must be >= 1."
                )
            return (pages_spec,)

        if isinstance(pages_spec, (list, tuple)):
            raw_tokens = [str(x) for x in pages_spec]
        elif isinstance(pages_spec, str):
            raw_tokens = pages_spec.split(",")
        else:
            raise InvalidInputError(
                f"Invalid 'pages' option type {type(pages_spec).__name__!r}. Expected str, int, or sequence."
            )

        selected: list[int] = []
        for raw in raw_tokens:
            token = raw.strip()
            if not token:
                continue

            if "-" in token:
                parts = token.split("-")
                if len(parts) != 2:
                    raise InvalidInputError(f"Invalid page range format: {token!r}")
                start_str, end_str = parts[0].strip(), parts[1].strip()
                if not start_str.isdigit() or not end_str.isdigit():
                    raise InvalidInputError(f"Non-numeric page range: {token!r}")
                start, end = int(start_str), int(end_str)
                if start < 1:
                    raise InvalidInputError(f"Page range start must be >= 1, got {start} in {token!r}")
                if end > total_pages:
                    raise InvalidInputError(
                        f"Page number {end} exceeds total pages {total_pages} in {token!r}"
                    )
                if start > end:
                    raise InvalidInputError(
                        f"Invalid inverted page range: {start} > {end} in {token!r}"
                    )
                for p in range(start, end + 1):
                    selected.append(p)
            else:
                if not token.isdigit():
                    raise InvalidInputError(f"Invalid page token: {token!r}")
                p = int(token)
                if p < 1:
                    raise InvalidInputError(f"Page number must be >= 1, got {p}")
                if p > total_pages:
                    raise InvalidInputError(
                        f"Page number {p} exceeds total pages {total_pages}."
                    )
                selected.append(p)

        if not selected:
            raise InvalidInputError("No valid pages selected for conversion.")

        # De-duplicate while preserving insertion order
        seen = set()
        deduped = tuple(p for p in selected if not (p in seen or seen.add(p)))
        return deduped

    @classmethod
    def validate_options(
        cls,
        options: dict[str, Any],
        target_format: str = "png",
        total_pages: Optional[int] = None,
    ) -> dict[str, Any]:
        """Validate options dictionary for PDF to image export."""
        target_norm = target_format.lower().strip().lstrip(".")
        validated = dict(options)

        if "dpi" in options:
            try:
                dpi = int(options["dpi"])
            except (ValueError, TypeError) as exc:
                raise InvalidInputError(f"DPI must be an integer between {PdfPageRenderer.MIN_DPI} and {PdfPageRenderer.MAX_DPI}, got {options['dpi']!r}") from exc
            if dpi < PdfPageRenderer.MIN_DPI or dpi > PdfPageRenderer.MAX_DPI:
                raise InvalidInputError(
                    f"DPI must be an integer between {PdfPageRenderer.MIN_DPI} and {PdfPageRenderer.MAX_DPI}, got {dpi}."
                )
            validated["dpi"] = dpi

        if "quality" in options:
            if target_norm not in ("jpeg", "jpg"):
                raise InvalidInputError(f"Option 'quality' is only valid for JPEG output, not {target_norm!r}.")
            try:
                q = int(options["quality"])
            except (ValueError, TypeError) as exc:
                raise InvalidInputError(f"JPEG quality must be an integer between 1 and 100, got {options['quality']!r}") from exc
            if q < 1 or q > 100:
                raise InvalidInputError(f"JPEG quality must be an integer between 1 and 100, got {q}.")
            validated["quality"] = q

        if "jpeg_background" in options:
            if target_norm not in ("jpeg", "jpg"):
                raise InvalidInputError(f"Option 'jpeg_background' is only valid for JPEG output, not {target_norm!r}.")
            bg = options["jpeg_background"]
            if not isinstance(bg, (tuple, list)) or len(bg) != 3 or not all(isinstance(c, int) and 0 <= c <= 255 for c in bg):
                raise InvalidInputError(f"Option 'jpeg_background' must be an RGB tuple of 3 integers (0–255), got {bg!r}")
            validated["jpeg_background"] = tuple(bg)

        pattern = options.get("output_pattern") or options.get("output_naming")
        if pattern is not None:
            if not isinstance(pattern, str) or not pattern.strip():
                raise InvalidInputError("Output pattern must be a non-empty string.")
            # Disallow directory separators and parent directory traversal
            if any(sep in pattern for sep in ("/", "\\", "..")):
                raise InvalidInputError(
                    f"Output pattern {pattern!r} contains forbidden path directory separators or parent directory traversal."
                )

        if total_pages is not None and "pages" in options:
            validated["pages"] = cls.parse_page_selection(options["pages"], total_pages)

        return validated

    @classmethod
    def export_pdf_to_images(
        cls,
        source_pdf: Path,
        output_dir: Path,
        target_format: str,
        *,
        options: Optional[dict[str, Any]] = None,
        max_input_bytes: Optional[int] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> tuple[tuple[Path, ...], int]:
        """Convert selected PDF pages to images and place them atomically.

        Parameters
        ----------
        source_pdf:
            Path to the source PDF document.
        output_dir:
            Directory where output images will be placed.
        target_format:
            Target image format ('png' or 'jpeg').
        options:
            Conversion options ('dpi', 'pages', 'quality', 'output_pattern', etc.).
        max_input_bytes:
            Maximum permitted input file size.
        cancel_check:
            Optional callable returning True if cancellation was requested.

        Returns
        -------
        tuple[tuple[Path, ...], int]
            Tuple of resolved output Paths and total written bytes.
        """
        from ..converter import reserve_output_path, _validate_no_source_dest_collision

        opts = options or {}
        target_norm = target_format.lower().strip().lstrip(".")
        if target_norm == "jpg":
            target_norm = "jpeg"
        if target_norm not in ("png", "jpeg"):
            raise InvalidInputError(f"Unsupported target format for PDF export: {target_format!r}")

        cls.validate_options(opts, target_norm)

        source_pdf = Path(source_pdf).resolve()
        output_dir = Path(output_dir).resolve()
        output_dir.mkdir(parents=True, exist_ok=True)

        if cancel_check and cancel_check():
            raise ConversionCancelledError("Conversion was cancelled before export started.")

        if not source_pdf.is_file():
            raise InvalidInputError(f"Input file does not exist or is not a regular file: {source_pdf}")

        file_size = source_pdf.stat().st_size
        if file_size == 0:
            raise InvalidInputError(f"Input PDF file is empty (0 bytes): {source_pdf}")
        if max_input_bytes and file_size > max_input_bytes:
            raise InputTooLargeError(
                f"Input file size ({file_size} bytes) exceeds limit of {max_input_bytes} bytes."
            )

        # 1. Structural inspection via PdfInspector
        inspection = PdfInspector.inspect(source_pdf)
        if inspection.is_encrypted:
            raise InvalidInputError(
                f"PDF document is password-protected/encrypted and cannot be converted without credentials: {source_pdf.name}"
            )
        if not inspection.is_readable:
            raise InvalidInputError(f"Corrupted or invalid PDF document: {inspection.error or source_pdf.name}")
        if inspection.page_count < 1:
            raise InvalidInputError(f"PDF document contains 0 pages: {source_pdf.name}")
        if inspection.page_count > MAX_PAGES_LIMIT:
            raise InputTooLargeError(
                f"PDF page count ({inspection.page_count}) exceeds limit of {MAX_PAGES_LIMIT} pages."
            )

        # 2. Page selection
        pages_spec = opts.get("pages", "all")
        selected_pages = cls.parse_page_selection(pages_spec, inspection.page_count)

        # 3. Resolve options
        dpi = int(opts.get("dpi", PdfPageRenderer.DEFAULT_DPI))
        quality = int(opts.get("quality", 90)) if target_norm == "jpeg" else 90
        jpeg_bg = tuple(opts.get("jpeg_background", (255, 255, 255)))

        custom_pattern = opts.get("output_pattern") or opts.get("output_naming")
        if custom_pattern:
            pattern = custom_pattern.strip()
            # If multiple pages are exported, pattern must have page indicator
            if len(selected_pages) > 1 and not re.search(r"\{page(?::[^}]*)?\}", pattern):
                raise InvalidInputError(
                    f"Output pattern {pattern!r} must contain '{{page}}' placeholder when exporting multiple pages."
                )
        else:
            # Default naming: multipage uses {stem}_page_{page}.{ext}, single page uses {stem}.{ext}
            if len(selected_pages) > 1 or inspection.page_count > 1:
                pattern = "{stem}_page_{page}.{ext}"
            else:
                pattern = "{stem}.{ext}"

        # 4. Rendering and atomic placement
        created_outputs: list[Path] = []
        temp_files: list[Path] = []
        reservations: list[Any] = []

        try:
            doc = pypdfium2.PdfDocument(source_pdf)
            for page_num in selected_pages:
                if cancel_check and cancel_check():
                    raise ConversionCancelledError(f"Conversion cancelled during page {page_num} export.")

                # Compute destination filename
                ext = "jpg" if target_norm == "jpeg" and ".jpg" in pattern else target_norm
                try:
                    filename = pattern.format(
                        stem=source_pdf.stem,
                        page=page_num,
                        page_count=inspection.page_count,
                        ext=ext,
                    )
                except KeyError as exc:
                    raise InvalidInputError(f"Unknown placeholder {exc} in output pattern {pattern!r}.")

                dest_stem = Path(filename).stem
                dest_ext = Path(filename).suffix.lstrip(".") or target_norm

                # Reserve output path to prevent concurrent/in-process collisions
                res = reserve_output_path(output_dir, dest_stem, dest_ext)
                reservations.append(res)
                dest_path = res.path
                _validate_no_source_dest_collision(source_pdf, dest_path)

                # Render page
                page = doc[page_num - 1]
                arr = PdfPageRenderer.render_page(page, dpi=dpi)

                # Convert to PIL Image
                im = Image.fromarray(arr, mode="RGB")

                # If JPEG with alpha compositing requested (though arr is RGB)
                if target_norm == "jpeg" and im.mode == "RGBA":
                    bg = Image.new("RGB", im.size, color=jpeg_bg)
                    bg.paste(im, mask=im.split()[3])
                    im = bg

                # Write to secure temporary file
                fd, tmp_str = tempfile.mkstemp(
                    suffix=f".{dest_ext}.tmp",
                    dir=output_dir,
                    prefix=f".localshift_{dest_stem}_",
                )
                os.close(fd)
                tmp_p = Path(tmp_str)
                temp_files.append(tmp_p)

                if target_norm == "png":
                    im.save(tmp_p, format="PNG")
                else:
                    im.save(tmp_p, format="JPEG", quality=quality)

                # Explicitly release memory
                del arr
                del im

                # Atomically commit page
                os.replace(tmp_p, dest_path)
                temp_files.remove(tmp_p)
                created_outputs.append(dest_path)

            doc.close()

        except Exception:
            # Clean up all created files on failure or cancellation
            for tmp_p in temp_files:
                if tmp_p.exists():
                    try:
                        tmp_p.unlink()
                    except OSError:
                        pass
            for out_p in created_outputs:
                if out_p.exists():
                    try:
                        out_p.unlink()
                    except OSError:
                        pass
            raise
        finally:
            for r in reservations:
                r.release()

        total_bytes = sum(p.stat().st_size for p in created_outputs)
        return tuple(created_outputs), total_bytes


parse_page_selection = PdfToImageExporter.parse_page_selection
validate_options = PdfToImageExporter.validate_options
export_pdf_to_images = PdfToImageExporter.export_pdf_to_images
