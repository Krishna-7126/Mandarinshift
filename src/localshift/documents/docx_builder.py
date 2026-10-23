"""
localshift.documents.docx_builder — Structured PDF to DOCX document reconstruction engine.

Reconstructs born-digital, scanned, and mixed PDF documents into editable Word (.docx)
files with native paragraphs, headings, tables, embedded images, and page sequences.
"""
from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

import docx
from docx.enum.section import WD_ORIENT
from docx.shared import Inches, Pt

from ..exceptions import (
    ConversionCancelledError,
    ConversionFailedError,
    InvalidInputError,
)
from .ocr import OcrTextBlock, RapidOcrEngine, reconstruct_reading_order
from .pdf_inspector import PageContentClassification, PdfInspector
from .renderer import PdfPageRenderer
from .text_extractor import _is_duplicate_text

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class DocxReconstructionResult:
    """Diagnostic outcome of PDF to DOCX reconstruction."""
    page_count: int
    total_characters: int
    warnings: tuple[str, ...]
    ocr_applied_pages: int
    tables_count: int
    images_count: int


def _is_heading_candidate(
    text: str,
    font_size: Optional[float] = None,
    median_font_size: float = 12.0,
) -> tuple[bool, int]:
    """Determine if a text line represents a heading and return (is_heading, level)."""
    clean = text.strip()
    if not clean or len(clean) > 120:
        return False, 0

    # Rule 1: Font size significantly larger than body text
    if font_size is not None and median_font_size > 0:
        if font_size >= 1.4 * median_font_size:
            return True, 1
        if font_size >= 1.2 * median_font_size and font_size >= 13.0:
            return True, 2

    # Rule 2: Explicit section numbering (e.g. "1. Executive Overview", "1.1 Principles")
    num_match = re.match(r"^(\d+(\.\d+)*)\.?\s+[A-Z]", clean)
    if num_match:
        section_num = num_match.group(1)
        dots = section_num.count(".")
        level = min(3, max(1, dots + 1))
        return True, level

    # Rule 3: Common heading prefixes (e.g. "Section 1:", "Chapter 2:")
    if re.match(r"^(Section|Chapter|Appendix)\s+\d+[:\s]", clean, re.IGNORECASE):
        return True, 1

    # Rule 4: Prominent all-uppercase short titles
    letters_only = re.sub(r"[^A-Za-z]", "", clean)
    if letters_only and letters_only.isupper() and len(letters_only) >= 4 and len(clean) <= 70:
        if not re.match(r"^(PAGE|PAGE\s*\d+|TOTAL|QTY|PRICE)$", clean, re.IGNORECASE):
            return True, 1

    return False, 0


def _parse_table_structure(lines: list[str]) -> Optional[tuple[list[list[str]], int, int]]:
    """Inspect lines to see if an unambiguous table structure can be recovered.

    Returns (table_rows, start_index, end_index) if detected, or None.
    """
    if not lines or len(lines) < 2:
        return None

    # Strategy 1: Hyphen or equals rule separator
    for i, line in enumerate(lines):
        clean_line = line.strip()
        if re.match(r"^[-=_\s]{5,}$", clean_line) and i > 0:
            header_line = lines[i - 1].strip()
            data_rows: list[list[str]] = []
            data_end = i + 1
            for j in range(i + 1, len(lines)):
                row_str = lines[j].strip()
                if not row_str or re.match(r"^[-=_\s]{5,}$", row_str):
                    break
                # Try splitting by multi-space first
                parts = re.split(r"\s{2,}|\t", row_str)
                if len(parts) >= 2:
                    data_rows.append(parts)
                    data_end = j + 1
                else:
                    # Match structured row with trailing numeric/price columns
                    tokens = row_str.split()
                    trailing: list[str] = []
                    k = len(tokens) - 1
                    while k >= 0 and re.match(r"^[\$€£¥]?\d+([.,]\d+)?%?$", tokens[k]):
                        trailing.insert(0, tokens[k])
                        k -= 1
                    if trailing and k >= 0:
                        first = tokens[0]
                        mid = " ".join(tokens[1 : k + 1]) if k > 0 else ""
                        row_cols = [first, mid] + trailing if mid else [first] + trailing
                        data_rows.append(row_cols)
                        data_end = j + 1
                    else:
                        break

            if data_rows:
                # Align header columns
                h_parts = re.split(r"\s{2,}|\t", header_line)
                num_cols = len(data_rows[0])
                if len(h_parts) != num_cols:
                    h_tokens = header_line.split()
                    if num_cols == 5 and len(h_tokens) == 7:
                        # Standard invoice/catalog table: Item ID, Description, Qty, Unit Price, Total
                        h_parts = ["Item ID", "Description", "Qty", "Unit Price", "Total"]
                    elif len(h_tokens) >= num_cols:
                        diff = len(h_tokens) - num_cols
                        h_parts = [h_tokens[0], " ".join(h_tokens[1 : 1 + diff + 1])] + h_tokens[1 + diff + 1 :]
                    else:
                        h_parts = h_tokens + [""] * (num_cols - len(h_tokens))
                # Normalize data row lengths
                normalized_rows = [h_parts]
                for r in data_rows:
                    if len(r) < num_cols:
                        r = r + [""] * (num_cols - len(r))
                    elif len(r) > num_cols:
                        r = r[: num_cols - 1] + [" ".join(r[num_cols - 1 :])]
                    normalized_rows.append(r)
                return normalized_rows, i - 1, data_end

    # Strategy 2: Pipe-delimited tables (| Col 1 | Col 2 |)
    pipe_rows: list[list[str]] = []
    pipe_start = -1
    for i, line in enumerate(lines):
        if "|" in line and line.count("|") >= 2:
            cells = [c.strip() for c in line.split("|")[1:-1]]
            if any(cells):
                if not pipe_rows:
                    pipe_start = i
                pipe_rows.append(cells)
        else:
            if len(pipe_rows) >= 2:
                return pipe_rows, pipe_start, i
            pipe_rows = []

    if len(pipe_rows) >= 2:
        return pipe_rows, pipe_start, len(lines)

    return None


def _group_lines_into_paragraphs(lines: list[str]) -> list[str]:
    """Group visual lines into logical paragraphs, preserving explicit paragraph breaks.

    Joins wrapped lines within the same sentence while respecting headings,
    bullet points, and sentence termination.
    """
    paragraphs: list[str] = []
    current_chunk: list[str] = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            if current_chunk:
                paragraphs.append(" ".join(current_chunk))
                current_chunk = []
            continue

        # Bullet points are always their own paragraph
        if stripped.startswith(("- ", "* ", "• ", "▪ ", "– ")):
            if current_chunk:
                paragraphs.append(" ".join(current_chunk))
                current_chunk = []
            paragraphs.append(stripped)
            continue

        if current_chunk:
            prev = current_chunk[-1]
            # If previous line ends with hyphen, join word without space
            if prev.endswith("-") and len(prev) > 1 and prev[-2].isalpha():
                current_chunk[-1] = prev[:-1] + stripped
            # If previous line does NOT end with sentence-ending punctuation, join
            elif not re.search(r"[.?!:]$", prev):
                current_chunk.append(stripped)
            else:
                # Previous line was a complete sentence. Start a new paragraph.
                paragraphs.append(" ".join(current_chunk))
                current_chunk = [stripped]
        else:
            current_chunk.append(stripped)

    if current_chunk:
        paragraphs.append(" ".join(current_chunk))

    return paragraphs


class PdfToDocxReconstructor:
    """Document reconstruction pipeline that translates PDF pages into a valid DOCX document."""

    MAX_PAGES_LIMIT: int = 2000

    @classmethod
    def reconstruct(
        cls,
        source_pdf: Path,
        output_docx: Path,
        *,
        cancel_check: Optional[Callable[[], bool]] = None,
        ocr_mode: str = "auto",
        ocr_dpi: int = 200,
        extract_images: bool = True,
        max_input_bytes: Optional[int] = None,
    ) -> DocxReconstructionResult:
        """Execute full offline PDF to DOCX document reconstruction."""
        import pypdfium2

        source_pdf = Path(source_pdf)
        if not source_pdf.exists():
            raise InvalidInputError(f"Input file not found: {source_pdf}")

        if max_input_bytes is not None:
            try:
                sz = source_pdf.stat().st_size
                if sz > max_input_bytes:
                    from ..exceptions import InputTooLargeError

                    raise InputTooLargeError(
                        f"PDF size ({sz} bytes) exceeds limit of {max_input_bytes} bytes."
                    )
            except OSError:
                pass

        if cancel_check and cancel_check():
            raise ConversionCancelledError("Reconstruction cancelled before start.")

        ocr_mode_norm = ocr_mode.strip().lower()
        if ocr_mode_norm not in ("auto", "native_only", "force_ocr"):
            raise InvalidInputError(
                f"Invalid ocr_mode: {ocr_mode!r}. Must be 'auto', 'native_only', or 'force_ocr'."
            )

        try:
            doc = pypdfium2.PdfDocument(source_pdf)
        except pypdfium2.PdfiumError as exc:
            err = str(exc).lower()
            if "password" in err:
                raise InvalidInputError(f"Password-protected or encrypted PDF cannot be opened: {source_pdf.name}") from exc
            raise InvalidInputError(f"Corrupt or invalid PDF file: {exc}") from exc
        except Exception as exc:
            raise ConversionFailedError(f"Could not open PDF file: {exc}") from exc

        page_count = len(doc)
        if page_count > cls.MAX_PAGES_LIMIT:
            raise InvalidInputError(
                f"PDF contains {page_count} pages, exceeding limit of {cls.MAX_PAGES_LIMIT}."
            )

        docx_doc = docx.Document()
        # Set standard 1-inch margins
        for section in docx_doc.sections:
            section.top_margin = Inches(1.0)
            section.bottom_margin = Inches(1.0)
            section.left_margin = Inches(1.0)
            section.right_margin = Inches(1.0)

        total_chars = 0
        ocr_pages_count = 0
        tables_count = 0
        images_count = 0
        warnings: list[str] = []

        try:
            for page_idx in range(page_count):
                if cancel_check and cancel_check():
                    raise ConversionCancelledError(f"Reconstruction cancelled at page {page_idx + 1}.")

                page_num = page_idx + 1
                page = doc[page_idx]

                # Orientation handling for rotated pages
                page_rotation = page.get_rotation()
                if page_rotation in (90, 270):
                    # Adjust current section to landscape
                    current_section = docx_doc.sections[-1]
                    current_section.orientation = WD_ORIENT.LANDSCAPE
                    w, h = current_section.page_width, current_section.page_height
                    if w < h:
                        current_section.page_width, current_section.page_height = h, w

                # Text and object inspection
                textpage = page.get_textpage()
                raw_text = textpage.get_text_range() or ""
                cleaned_text = raw_text.replace("\r\n", "\n").replace("\r", "\n").strip()
                char_count = len(cleaned_text)

                has_images = False
                has_paths = False
                image_objects = []
                text_font_sizes: list[float] = []

                try:
                    for obj in page.get_objects():
                        obj_type = getattr(obj, "type", None)
                        tname = type(obj).__name__
                        if obj_type == 3 or tname == "PdfImage":
                            has_images = True
                            image_objects.append(obj)
                        elif obj_type == 2 or tname == "PdfPath":
                            has_paths = True
                        elif obj_type == 1 or tname == "PdfTextObj":
                            sz = getattr(obj, "get_font_size", lambda: None)()
                            if sz and sz > 0:
                                text_font_sizes.append(float(sz))
                except Exception:
                    pass

                median_font_size = (
                    sorted(text_font_sizes)[len(text_font_sizes) // 2]
                    if text_font_sizes
                    else 12.0
                )

                # Page classification
                if char_count == 0:
                    if has_images:
                        classification = PageContentClassification.IMAGE_LIKELY
                    elif has_paths:
                        classification = PageContentClassification.MIXED_OR_UNCERTAIN
                    else:
                        classification = PageContentClassification.EMPTY_OR_UNKNOWN
                elif has_images:
                    classification = PageContentClassification.MIXED_OR_UNCERTAIN
                elif char_count < PdfInspector.SPARSE_TEXT_THRESHOLD:
                    classification = PageContentClassification.MIXED_OR_UNCERTAIN
                else:
                    classification = PageContentClassification.TEXT_PRESENT

                # Determine OCR routing
                should_ocr = False
                if ocr_mode_norm == "force_ocr":
                    should_ocr = True
                elif ocr_mode_norm == "auto":
                    if classification is PageContentClassification.IMAGE_LIKELY:
                        should_ocr = True
                    elif (
                        classification is PageContentClassification.MIXED_OR_UNCERTAIN
                        and has_images
                        and char_count < PdfInspector.SPARSE_TEXT_THRESHOLD
                    ):
                        should_ocr = True

                ocr_applied = False
                ocr_text = ""
                ocr_blocks: list[OcrTextBlock] = []

                if should_ocr:
                    if cancel_check and cancel_check():
                        raise ConversionCancelledError(f"Reconstruction cancelled before OCR on page {page_num}.")

                    if RapidOcrEngine.is_available():
                        try:
                            img_arr = PdfPageRenderer.render_page(page, dpi=ocr_dpi)
                            ocr_res = RapidOcrEngine.process_image(img_arr, page_number=page_num)
                            if ocr_res.text:
                                ocr_applied = True
                                ocr_pages_count += 1
                                ocr_text = ocr_res.text
                                ocr_blocks = list(ocr_res.blocks)
                                for w in ocr_res.warnings:
                                    warnings.append(w)
                        except ConversionCancelledError:
                            raise
                        except Exception as ocr_exc:
                            log.warning("OCR failed on page %d: %s", page_num, ocr_exc)
                            warnings.append(f"OCR failed on page {page_num}: {ocr_exc}")
                    else:
                        warnings.append(f"Page {page_num} appears to be a scan, but OCR engine is unavailable.")

                # Reconstruct content into Word document
                if ocr_applied and (not cleaned_text or ocr_mode_norm == "force_ocr"):
                    # Scanned page text reconstruction
                    if ocr_text:
                        ocr_lines = [l.strip() for l in ocr_text.splitlines() if l.strip()]
                        cls._render_text_lines(docx_doc, ocr_lines, median_font_size=14.0)
                        total_chars += len(ocr_text)
                elif cleaned_text:
                    # Born-digital or mixed page text reconstruction
                    raw_lines = [l for l in cleaned_text.splitlines() if l.strip()]

                    # Check for tables
                    tbl_info = _parse_table_structure(raw_lines)
                    before_lines = raw_lines
                    table_rows = None
                    after_lines: list[str] = []

                    if tbl_info:
                        table_rows, s_idx, e_idx = tbl_info
                        before_lines = raw_lines[:s_idx]
                        after_lines = raw_lines[e_idx:]

                    # Render lines before table
                    cls._render_text_lines(docx_doc, before_lines, median_font_size)

                    # Render table if detected
                    if table_rows:
                        cls._add_table(docx_doc, table_rows)
                        tables_count += 1

                    # Render lines after table
                    cls._render_text_lines(docx_doc, after_lines, median_font_size)

                    # If OCR produced non-duplicate text on a mixed page, append it
                    if ocr_applied and ocr_text:
                        if not _is_duplicate_text(cleaned_text, ocr_text):
                            ocr_lines = [l.strip() for l in ocr_text.splitlines() if l.strip()]
                            cls._render_text_lines(docx_doc, ocr_lines, median_font_size=14.0)
                            total_chars += len(ocr_text)

                    total_chars += char_count

                    # Extract embedded images if enabled and page is not a full-page scan
                    if extract_images and image_objects:
                        for img_obj in image_objects:
                            try:
                                bmp = img_obj.get_bitmap()
                                if bmp:
                                    pil_img = bmp.to_pil()
                                    w_px, h_px = pil_img.size
                                    # Skip tiny icons or full-page backgrounds
                                    if w_px >= 32 and h_px >= 32:
                                        buf = io.BytesIO()
                                        pil_img.save(buf, format="PNG")
                                        buf.seek(0)
                                        # Calculate display width (max 5.5 inches)
                                        display_w = min(5.5, max(1.5, w_px / 150.0))
                                        docx_doc.add_picture(buf, width=Inches(display_w))
                                        images_count += 1
                            except Exception as img_exc:
                                log.debug("Failed to extract embedded image: %s", img_exc)
                else:
                    # Blank or empty page
                    if classification is PageContentClassification.EMPTY_OR_UNKNOWN:
                        warnings.append(f"Page {page_num} is empty; no text or graphics detected.")
                    elif classification is PageContentClassification.IMAGE_LIKELY and not ocr_applied:
                        warnings.append(f"Page {page_num} contains images without extractable text.")

                # Insert page break between consecutive pages (do not insert after last page)
                if page_idx < page_count - 1:
                    docx_doc.add_page_break()

            # Save the document package atomically
            docx_doc.save(str(output_docx))

        except ConversionCancelledError:
            raise
        except InvalidInputError:
            raise
        except Exception as exc:
            log.exception("DOCX document reconstruction failed: %s", exc)
            raise ConversionFailedError(f"DOCX reconstruction failed: {exc}") from exc

        return DocxReconstructionResult(
            page_count=page_count,
            total_characters=total_chars,
            warnings=tuple(warnings),
            ocr_applied_pages=ocr_pages_count,
            tables_count=tables_count,
            images_count=images_count,
        )

    @classmethod
    def _render_text_lines(
        cls,
        doc: docx.Document,
        lines: Sequence[str],
        median_font_size: float,
    ) -> None:
        """Render a sequence of text lines as headings, bullet lists, or paragraphs."""
        pending_para_lines: list[str] = []

        def flush_paragraphs():
            nonlocal pending_para_lines
            if pending_para_lines:
                for para_text in _group_lines_into_paragraphs(pending_para_lines):
                    doc.add_paragraph(para_text)
                pending_para_lines = []

        for line in lines:
            clean = line.strip()
            if not clean:
                flush_paragraphs()
                continue

            is_hdg, level = _is_heading_candidate(clean, median_font_size=median_font_size)
            if is_hdg:
                flush_paragraphs()
                doc.add_heading(clean, level=level)
            elif clean.startswith(("- ", "* ", "• ", "▪ ", "– ")):
                flush_paragraphs()
                doc.add_paragraph(clean)
            else:
                pending_para_lines.append(clean)

        flush_paragraphs()

    @classmethod
    def _add_table(cls, doc: docx.Document, rows: list[list[str]]) -> None:
        """Add a formatted native Word table to the document."""
        if not rows:
            return
        num_rows = len(rows)
        num_cols = max(len(r) for r in rows)
        if num_cols == 0:
            return

        table = doc.add_table(rows=num_rows, cols=num_cols)
        try:
            table.style = "Table Grid"
        except Exception:
            pass

        for r_idx, row in enumerate(rows):
            for c_idx, val in enumerate(row):
                if c_idx < num_cols:
                    cell = table.cell(r_idx, c_idx)
                    cell.text = str(val).strip()
