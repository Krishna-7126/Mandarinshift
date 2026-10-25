"""
localshift.documents.pdf_workbench — Offline PDF Workbench: Merge, Split, Reorder & Rotate.

Provides high-performance, fully offline PDF manipulation:
- Merge: Combine multiple PDF documents in an explicitly defined order.
- Split: Split PDF documents into individual single-page files or extract page subsets.
- Reorder: Rearrange pages according to a validated page-index sequence.
- Rotate: Rotate selected pages by 90°, 180°, or 270° (relative or absolute).

Reliability & Security Guarantees:
- Safe structural inspection via PdfInspector (traps encrypted, corrupt, and empty PDFs).
- Respects ISO 32000 limits and MAX_PAGES_LIMIT (2000 pages).
- Inputs are opened read-only and never modified in place.
- Collision-free in-process reservations and atomic file placement via temporary files.
- Cooperative cancellation and complete cleanup on failure.
- 100% offline, permissively licensed (pypdfium2 / Apache-2.0 / BSD-3).
"""
from __future__ import annotations

import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Callable, Optional, Sequence, Union

import pypdfium2

from ..converter import (
    MAX_INPUT_BYTES,
    OutputReservation,
    reserve_output_path,
    unique_output_path,
)
from ..exceptions import (
    ConversionCancelledError,
    ConversionFailedError,
    DestinationConflictError,
    InputTooLargeError,
    InvalidInputError,
)
from .pdf_image_exporter import MAX_PAGES_LIMIT, PdfToImageExporter
from .pdf_inspector import PdfInspector

log = logging.getLogger(__name__)

SUPPORTED_ROTATION_ANGLES: frozenset[int] = frozenset({0, 90, 180, 270})


def _validate_pdf_input(source: Path, max_input_bytes: int = MAX_INPUT_BYTES) -> None:
    """Validate that *source* exists, is a regular file, fits within size limits, and is a valid PDF."""
    if not source.exists():
        raise InvalidInputError(f"Input file not found: {source}")
    if not source.is_file():
        raise InvalidInputError(f"Input path is not a regular file: {source}")

    try:
        size = source.stat().st_size
    except OSError as exc:
        raise InvalidInputError(f"Cannot access input file {source}: {exc}") from exc

    if size > max_input_bytes:
        raise InputTooLargeError(
            f"Input file {source.name} ({size / (1024 * 1024):.1f} MiB) exceeds "
            f"maximum allowed size of {max_input_bytes / (1024 * 1024):.0f} MiB."
        )

    # Check magic bytes '%PDF-'
    try:
        with open(source, "rb") as f:
            header = f.read(5)
        if not header.startswith(b"%PDF-"):
            raise InvalidInputError(
                f"File {source.name} does not have valid PDF magic bytes (%PDF-)."
            )
    except OSError as exc:
        raise InvalidInputError(f"Cannot read file header for {source}: {exc}") from exc

    # Inspect structural readability & encryption
    report = PdfInspector.inspect(source)
    if not report.is_readable:
        if report.is_encrypted:
            raise InvalidInputError(
                f"PDF file {source.name} is password-protected or encrypted."
            )
        raise InvalidInputError(
            f"PDF file {source.name} is corrupt or unreadable: {report.error or 'invalid structure'}."
        )
    if report.page_count < 1:
        raise InvalidInputError(f"PDF file {source.name} contains 0 pages.")


def _check_source_conflict(source: Path, output_path: Optional[Union[str, Path]]) -> None:
    """Raise DestinationConflictError if *output_path* matches *source*."""
    if output_path is None:
        return
    out = Path(output_path)
    try:
        src_real = source.resolve()
        out_real = out.resolve()
        same = src_real == out_real
        if not same and os.name == "nt":
            same = src_real.as_posix().lower() == out_real.as_posix().lower()
    except OSError:
        same = str(source).lower() == str(out).lower()

    if same:
        raise DestinationConflictError(
            f"Output path {out} is identical to source input {source}. "
            "LocalShift will never overwrite a source file."
        )


def _resolve_output_file(
    output_path: Optional[Union[str, Path]],
    output_dir: Optional[Union[str, Path]],
    fallback_folder: Path,
    stem: str,
    suffix: str = ".pdf",
) -> tuple[Path, OutputReservation]:
    """Resolve destination folder and filename, acquiring an in-process reservation."""
    ext = suffix.lstrip(".")
    if output_path is not None:
        target = Path(output_path)
        folder = target.parent
        target_stem = target.stem
    elif output_dir is not None:
        folder = Path(output_dir)
        target_stem = stem
    else:
        folder = fallback_folder
        target_stem = stem

    folder.mkdir(parents=True, exist_ok=True)
    reservation = reserve_output_path(folder, target_stem, ext)
    return reservation.path, reservation


class PdfWorkbench:
    """Offline PDF workbench providing merge, split, reorder, and rotation operations."""

    @classmethod
    def merge(
        cls,
        sources: Sequence[Union[str, Path]],
        output_path: Optional[Union[str, Path]] = None,
        output_dir: Optional[Union[str, Path]] = None,
        *,
        cancel_check: Optional[Callable[[], bool]] = None,
        max_input_bytes: int = MAX_INPUT_BYTES,
    ) -> Path:
        """Combine multiple PDF files into one in the specified order.

        Parameters
        ----------
        sources:
            Ordered list of input PDF file paths. Must contain at least 1 file.
        output_path:
            Explicit target path for the merged PDF.
        output_dir:
            Target directory. Ignored if output_path is specified.
        cancel_check:
            Optional callback polling for cooperative cancellation.
        max_input_bytes:
            Maximum allowed file size per input file.

        Returns
        -------
        Path
            Resolved path of the created merged PDF document.
        """
        if not sources:
            raise InvalidInputError("Merge operation requires at least 1 input PDF file.")

        resolved_sources = [Path(s).resolve() for s in sources]

        # Validate all inputs before touching destination
        total_pages = 0
        for src in resolved_sources:
            if cancel_check and cancel_check():
                raise ConversionCancelledError("Merge operation cancelled.")
            _validate_pdf_input(src, max_input_bytes=max_input_bytes)
            report = PdfInspector.inspect(src)
            total_pages += report.page_count

        if total_pages > MAX_PAGES_LIMIT:
            raise InputTooLargeError(
                f"Combined page count ({total_pages}) exceeds maximum allowed "
                f"limit of {MAX_PAGES_LIMIT} pages."
            )

        if output_path is not None:
            for s in resolved_sources:
                _check_source_conflict(s, output_path)

        dest_path, reservation = _resolve_output_file(
            output_path=output_path,
            output_dir=output_dir,
            fallback_folder=resolved_sources[0].parent,
            stem=f"{resolved_sources[0].stem}_merged",
        )

        for src in resolved_sources:
            if src == dest_path.resolve():
                reservation.release()
                raise DestinationConflictError(
                    f"Output path {dest_path} is identical to source input {src}. "
                    "LocalShift will never overwrite a source file."
                )

        target_dir = dest_path.parent
        fd, tmp_str = tempfile.mkstemp(dir=target_dir, prefix="localshift_merge_", suffix=".tmp")
        os.close(fd)
        tmp_path = Path(tmp_str)

        merged_doc = pypdfium2.PdfDocument.new()
        open_docs: list[pypdfium2.PdfDocument] = []
        try:
            for src in resolved_sources:
                if cancel_check and cancel_check():
                    raise ConversionCancelledError("Merge operation cancelled.")
                src_doc = pypdfium2.PdfDocument(src)
                open_docs.append(src_doc)
                merged_doc.import_pages(src_doc)

            if cancel_check and cancel_check():
                raise ConversionCancelledError("Merge operation cancelled.")

            merged_doc.save(tmp_path)
            merged_doc.close()

            for doc in open_docs:
                doc.close()
            open_docs.clear()

            os.replace(tmp_path, dest_path)
            return dest_path
        except Exception:
            for doc in open_docs:
                try:
                    doc.close()
                except Exception:
                    pass
            try:
                merged_doc.close()
            except Exception:
                pass
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
            raise
        finally:
            reservation.release()

    @classmethod
    def split(
        cls,
        source: Union[str, Path],
        output_dir: Optional[Union[str, Path]] = None,
        pages: Any = "all",
        output_pattern: Optional[str] = None,
        *,
        cancel_check: Optional[Callable[[], bool]] = None,
        max_input_bytes: int = MAX_INPUT_BYTES,
    ) -> tuple[Path, ...]:
        """Split a PDF into individual single-page PDF files.

        Parameters
        ----------
        source:
            Input PDF file path.
        output_dir:
            Target directory for split files. Defaults to source parent folder.
        pages:
            Page selection string, int, or sequence (e.g. 'all', '1-5', '1, 3').
        output_pattern:
            Custom naming pattern with tokens {stem}, {page}, {page_count}, {ext}.
            Defaults to '{stem}_page_{page}.pdf'.
        cancel_check:
            Optional callback polling for cooperative cancellation.
        max_input_bytes:
            Maximum allowed file size.

        Returns
        -------
        tuple[Path, ...]
            Ordered tuple of paths to the generated split PDF files.
        """
        src = Path(source).resolve()
        _validate_pdf_input(src, max_input_bytes=max_input_bytes)
        report = PdfInspector.inspect(src)
        selected_pages = PdfToImageExporter.parse_page_selection(pages, report.page_count)

        target_dir = Path(output_dir).resolve() if output_dir is not None else src.parent
        target_dir.mkdir(parents=True, exist_ok=True)

        pattern = output_pattern or "{stem}_page_{page}.pdf"
        if "/" in pattern or "\\" in pattern or ".." in pattern:
            raise InvalidInputError(
                f"Output pattern {pattern!r} must not contain directory separators or parent traversal."
            )
        if len(selected_pages) > 1 and not re.search(r"\{page(?:[:!][^}]+)?\}", pattern):
            raise InvalidInputError(
                f"Output pattern {pattern!r} must include '{{page}}' when splitting multiple pages."
            )

        reservations: list[OutputReservation] = []
        created_paths: list[Path] = []
        temp_paths: list[Path] = []
        src_doc = pypdfium2.PdfDocument(src)

        try:
            for page_num in selected_pages:
                if cancel_check and cancel_check():
                    raise ConversionCancelledError("Split operation cancelled.")

                filename = pattern.format(
                    stem=src.stem,
                    page=page_num,
                    page_count=report.page_count,
                    ext="pdf",
                )
                if not filename.lower().endswith(".pdf"):
                    filename += ".pdf"
                dest_stem = Path(filename).stem

                res = reserve_output_path(target_dir, dest_stem, "pdf")
                reservations.append(res)
                dest_path = res.path

                if dest_path.resolve() == src:
                    raise DestinationConflictError(
                        f"Split output {dest_path} collides with input file {src}."
                    )

                fd, tmp_str = tempfile.mkstemp(dir=target_dir, prefix="localshift_split_", suffix=".tmp")
                os.close(fd)
                tmp_path = Path(tmp_str)
                temp_paths.append(tmp_path)

                single_page_doc = pypdfium2.PdfDocument.new()
                single_page_doc.import_pages(src_doc, [page_num - 1])
                single_page_doc.save(tmp_path)
                single_page_doc.close()

                os.replace(tmp_path, dest_path)
                created_paths.append(dest_path)

            src_doc.close()
            return tuple(created_paths)
        except Exception:
            try:
                src_doc.close()
            except Exception:
                pass
            for t in temp_paths:
                if t.exists():
                    try:
                        t.unlink()
                    except OSError:
                        pass
            for c in created_paths:
                if c.exists():
                    try:
                        c.unlink()
                    except OSError:
                        pass
            raise
        finally:
            for res in reservations:
                res.release()

    @classmethod
    def extract(
        cls,
        source: Union[str, Path],
        pages: Any,
        output_path: Optional[Union[str, Path]] = None,
        output_dir: Optional[Union[str, Path]] = None,
        *,
        cancel_check: Optional[Callable[[], bool]] = None,
        max_input_bytes: int = MAX_INPUT_BYTES,
    ) -> Path:
        """Extract a subset of pages from a PDF into a single new PDF document.

        Parameters
        ----------
        source:
            Input PDF file path.
        pages:
            Page specification (e.g. '1-3', '1, 3, 5').
        output_path:
            Explicit target path.
        output_dir:
            Target directory for extracted document.
        cancel_check:
            Optional callback polling for cooperative cancellation.
        max_input_bytes:
            Maximum allowed file size.

        Returns
        -------
        Path
            Resolved path of the created extracted PDF document.
        """
        src = Path(source).resolve()
        _validate_pdf_input(src, max_input_bytes=max_input_bytes)
        report = PdfInspector.inspect(src)
        selected_pages = PdfToImageExporter.parse_page_selection(pages, report.page_count)

        if not selected_pages:
            raise InvalidInputError("No pages selected for extraction.")

        _check_source_conflict(src, output_path)

        dest_path, reservation = _resolve_output_file(
            output_path=output_path,
            output_dir=output_dir,
            fallback_folder=src.parent,
            stem=f"{src.stem}_extracted",
        )

        if dest_path.resolve() == src:
            reservation.release()
            raise DestinationConflictError(
                f"Output path {dest_path} is identical to source input {src}."
            )

        target_dir = dest_path.parent
        fd, tmp_str = tempfile.mkstemp(dir=target_dir, prefix="localshift_extract_", suffix=".tmp")
        os.close(fd)
        tmp_path = Path(tmp_str)

        src_doc = pypdfium2.PdfDocument(src)
        extracted_doc = pypdfium2.PdfDocument.new()

        try:
            if cancel_check and cancel_check():
                raise ConversionCancelledError("Extract operation cancelled.")

            # import_pages accepts 0-based page index sequence
            extracted_doc.import_pages(src_doc, [p - 1 for p in selected_pages])

            if cancel_check and cancel_check():
                raise ConversionCancelledError("Extract operation cancelled.")

            extracted_doc.save(tmp_path)
            extracted_doc.close()
            src_doc.close()

            os.replace(tmp_path, dest_path)
            return dest_path
        except Exception:
            try:
                extracted_doc.close()
            except Exception:
                pass
            try:
                src_doc.close()
            except Exception:
                pass
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
            raise
        finally:
            reservation.release()

    @classmethod
    def reorder(
        cls,
        source: Union[str, Path],
        page_order: Sequence[int],
        output_path: Optional[Union[str, Path]] = None,
        output_dir: Optional[Union[str, Path]] = None,
        *,
        cancel_check: Optional[Callable[[], bool]] = None,
        max_input_bytes: int = MAX_INPUT_BYTES,
    ) -> Path:
        """Rearrange pages in a PDF document into the specified 1-based order.

        Parameters
        ----------
        source:
            Input PDF file path.
        page_order:
            1-based page index sequence (e.g. [3, 1, 2] or [2, 1]).
        output_path:
            Explicit target path.
        output_dir:
            Target directory.
        cancel_check:
            Optional callback polling for cooperative cancellation.
        max_input_bytes:
            Maximum allowed file size.

        Returns
        -------
        Path
            Resolved path of the created reordered PDF document.
        """
        src = Path(source).resolve()
        _validate_pdf_input(src, max_input_bytes=max_input_bytes)
        report = PdfInspector.inspect(src)

        if not page_order:
            raise InvalidInputError("Reorder operation requires a non-empty page_order sequence.")

        for idx, p in enumerate(page_order):
            if not isinstance(p, int):
                raise InvalidInputError(
                    f"Page index at position {idx} is not an integer: {p!r}."
                )
            if p < 1 or p > report.page_count:
                raise InvalidInputError(
                    f"Page number {p} in page_order is out of bounds (document has {report.page_count} pages)."
                )

        _check_source_conflict(src, output_path)

        dest_path, reservation = _resolve_output_file(
            output_path=output_path,
            output_dir=output_dir,
            fallback_folder=src.parent,
            stem=f"{src.stem}_reordered",
        )

        if dest_path.resolve() == src:
            reservation.release()
            raise DestinationConflictError(
                f"Output path {dest_path} is identical to source input {src}."
            )

        target_dir = dest_path.parent
        fd, tmp_str = tempfile.mkstemp(dir=target_dir, prefix="localshift_reorder_", suffix=".tmp")
        os.close(fd)
        tmp_path = Path(tmp_str)

        src_doc = pypdfium2.PdfDocument(src)
        reordered_doc = pypdfium2.PdfDocument.new()

        try:
            if cancel_check and cancel_check():
                raise ConversionCancelledError("Reorder operation cancelled.")

            reordered_doc.import_pages(src_doc, [p - 1 for p in page_order])

            if cancel_check and cancel_check():
                raise ConversionCancelledError("Reorder operation cancelled.")

            reordered_doc.save(tmp_path)
            reordered_doc.close()
            src_doc.close()

            os.replace(tmp_path, dest_path)
            return dest_path
        except Exception:
            try:
                reordered_doc.close()
            except Exception:
                pass
            try:
                src_doc.close()
            except Exception:
                pass
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
            raise
        finally:
            reservation.release()

    @classmethod
    def rotate(
        cls,
        source: Union[str, Path],
        rotation: int,
        pages: Any = "all",
        output_path: Optional[Union[str, Path]] = None,
        output_dir: Optional[Union[str, Path]] = None,
        *,
        relative: bool = True,
        cancel_check: Optional[Callable[[], bool]] = None,
        max_input_bytes: int = MAX_INPUT_BYTES,
    ) -> Path:
        """Rotate selected pages in a PDF document by 90, 180, or 270 degrees.

        Parameters
        ----------
        source:
            Input PDF file path.
        rotation:
            Angle in degrees (90, 180, 270, or negative equivalents like -90).
            Must be a multiple of 90 degrees.
        pages:
            Page specification (e.g. 'all', '1', '1-3', '2, 4').
        output_path:
            Explicit target path.
        output_dir:
            Target directory.
        relative:
            If True, rotation is added to current page rotation: (current + angle) % 360.
            If False, page rotation is set directly to angle % 360.
        cancel_check:
            Optional callback polling for cooperative cancellation.
        max_input_bytes:
            Maximum allowed file size.

        Returns
        -------
        Path
            Resolved path of the rotated PDF document.
        """
        src = Path(source).resolve()
        _validate_pdf_input(src, max_input_bytes=max_input_bytes)

        if not isinstance(rotation, int):
            raise InvalidInputError(f"Rotation angle must be an integer, got {type(rotation).__name__!r}.")

        angle = rotation % 360
        if angle not in SUPPORTED_ROTATION_ANGLES:
            raise InvalidInputError(
                f"Invalid rotation angle {rotation}°. Rotation must be a multiple of 90° (90, 180, 270)."
            )

        report = PdfInspector.inspect(src)
        selected_pages = set(PdfToImageExporter.parse_page_selection(pages, report.page_count))

        _check_source_conflict(src, output_path)

        dest_path, reservation = _resolve_output_file(
            output_path=output_path,
            output_dir=output_dir,
            fallback_folder=src.parent,
            stem=f"{src.stem}_rotated",
        )

        if dest_path.resolve() == src:
            reservation.release()
            raise DestinationConflictError(
                f"Output path {dest_path} is identical to source input {src}."
            )

        target_dir = dest_path.parent
        fd, tmp_str = tempfile.mkstemp(dir=target_dir, prefix="localshift_rotate_", suffix=".tmp")
        os.close(fd)
        tmp_path = Path(tmp_str)

        doc = pypdfium2.PdfDocument(src)
        try:
            for page_idx in range(len(doc)):
                if cancel_check and cancel_check():
                    raise ConversionCancelledError("Rotate operation cancelled.")
                page_num = page_idx + 1
                if page_num in selected_pages:
                    page = doc.get_page(page_idx)
                    if relative:
                        new_rot = (page.get_rotation() + angle) % 360
                    else:
                        new_rot = angle
                    page.set_rotation(new_rot)
                    page.close()

            if cancel_check and cancel_check():
                raise ConversionCancelledError("Rotate operation cancelled.")

            doc.save(tmp_path)
            doc.close()

            os.replace(tmp_path, dest_path)
            return dest_path
        except Exception:
            try:
                doc.close()
            except Exception:
                pass
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
            raise
        finally:
            reservation.release()


# ---------------------------------------------------------------------------
# Public Module-Level Convenience Functions
# ---------------------------------------------------------------------------

def merge_pdfs(
    sources: Sequence[Union[str, Path]],
    output_path: Optional[Union[str, Path]] = None,
    output_dir: Optional[Union[str, Path]] = None,
    *,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> Path:
    """Merge multiple PDF files into one ordered PDF document."""
    return PdfWorkbench.merge(
        sources=sources,
        output_path=output_path,
        output_dir=output_dir,
        cancel_check=cancel_check,
    )


def split_pdf(
    source: Union[str, Path],
    output_dir: Optional[Union[str, Path]] = None,
    pages: Any = "all",
    output_pattern: Optional[str] = None,
    *,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> tuple[Path, ...]:
    """Split a PDF file into individual single-page PDF files."""
    return PdfWorkbench.split(
        source=source,
        output_dir=output_dir,
        pages=pages,
        output_pattern=output_pattern,
        cancel_check=cancel_check,
    )


def extract_pdf_pages(
    source: Union[str, Path],
    pages: Any,
    output_path: Optional[Union[str, Path]] = None,
    output_dir: Optional[Union[str, Path]] = None,
    *,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> Path:
    """Extract a subset of pages from a PDF file into a single new PDF document."""
    return PdfWorkbench.extract(
        source=source,
        pages=pages,
        output_path=output_path,
        output_dir=output_dir,
        cancel_check=cancel_check,
    )


def reorder_pdf_pages(
    source: Union[str, Path],
    page_order: Sequence[int],
    output_path: Optional[Union[str, Path]] = None,
    output_dir: Optional[Union[str, Path]] = None,
    *,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> Path:
    """Rearrange the pages of a PDF document into a new 1-based order."""
    return PdfWorkbench.reorder(
        source=source,
        page_order=page_order,
        output_path=output_path,
        output_dir=output_dir,
        cancel_check=cancel_check,
    )


def rotate_pdf_pages(
    source: Union[str, Path],
    rotation: int,
    pages: Any = "all",
    output_path: Optional[Union[str, Path]] = None,
    output_dir: Optional[Union[str, Path]] = None,
    *,
    relative: bool = True,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> Path:
    """Rotate selected pages of a PDF file by 90°, 180°, or 270°."""
    return PdfWorkbench.rotate(
        source=source,
        rotation=rotation,
        pages=pages,
        output_path=output_path,
        output_dir=output_dir,
        relative=relative,
        cancel_check=cancel_check,
    )
