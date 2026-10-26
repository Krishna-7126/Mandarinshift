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

NUMERIC_CELL_PATTERN = re.compile(r"^[\(\[]?[\$€£¥]?-?\d[\d,]*(\.\d+)?%?[\)\]]?$")


@dataclass(frozen=True)
class DocxReconstructionResult:
    """Diagnostic outcome of PDF to DOCX reconstruction."""
    page_count: int
    total_characters: int
    warnings: tuple[str, ...]
    ocr_applied_pages: int
    tables_count: int
    images_count: int
    sanitized_characters_count: int = 0


# XML 1.0 valid character regex:
# Valid chars: \t (0x9), \n (0xA), \r (0xD), 0x20-0xD7FF, 0xE000-0xFFFD, 0x10000-0x10FFFF
_XML_INVALID_CHAR_RE = re.compile(
    r"[^\x09\x0A\x0D\x20-\uD7FF\uE000-\uFFFD\U00010000-\U0010FFFF]"
)


def sanitize_xml_text(text: str) -> tuple[str, int]:
    """Sanitize *text* to guarantee 100% XML 1.0 compatibility for Word/DOCX.

    Replaces form feed (\\x0c) and vertical tab (\\x0b) with newlines to preserve
    layout semantics. Strips NULL bytes (\\x00) and prohibited XML control
    characters (0x01-0x08, 0x0E-0x1F) and illegal surrogates while preserving
    valid whitespace (\\t, \\n, \\r), Unicode, CJK, and emoji.

    Returns (sanitized_string, count_of_sanitized_characters).
    """
    if not text:
        return "", 0
    t = text.replace("\x0c", "\n").replace("\x0b", "\n").replace("\x00", "")
    sanitized, count = _XML_INVALID_CHAR_RE.subn("", t)
    removed_count = count + (len(text) - len(t))
    return sanitized, removed_count


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

    # Rule 3: Common heading prefixes (e.g. "Section 1:", "Chapter 2:", "Article I:")
    if re.match(r"^(Section|Chapter|Article|Appendix)\s+([0-9]+|[IVXLCDM]+|[A-Z])([:\s\.\-\—]|$)", clean, re.IGNORECASE):
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
                    while k >= 0 and NUMERIC_CELL_PATTERN.match(tokens[k]):
                        trailing.insert(0, tokens[k])
                        k -= 1
                    if trailing and k >= 0:
                        h_tok_count = len(header_line.split())
                        expected_leading = max(1, h_tok_count - len(trailing))
                        if expected_leading == 1:
                            row_cols = [" ".join(tokens[: k + 1])] + trailing
                        else:
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

    # Strategy 3: Borderless / space-aligned multi-column tables (no rule separator)
    candidate_start = -1
    candidate_rows: list[list[str]] = []
    for i, line in enumerate(lines):
        clean = line.strip()
        if clean.startswith(("- ", "* ", "• ", "▪ ")) or _is_heading_candidate(clean)[0]:
            if len(candidate_rows) >= 2:
                max_cols = max(len(r) for r in candidate_rows)
                norm = [r + [""] * (max_cols - len(r)) for r in candidate_rows]
                return norm, candidate_start, i
            candidate_rows = []
            candidate_start = -1
            continue

        parts = [p.strip() for p in re.split(r"\s{2,}|\t", clean) if p.strip()]
        if len(parts) >= 2:
            if not candidate_rows:
                candidate_start = i
                candidate_rows.append(parts)
            else:
                expected_cols = len(candidate_rows[0])
                if abs(len(parts) - expected_cols) <= 1:
                    candidate_rows.append(parts)
                else:
                    if len(candidate_rows) >= 2:
                        max_cols = max(len(r) for r in candidate_rows)
                        norm = [r + [""] * (max_cols - len(r)) for r in candidate_rows]
                        return norm, candidate_start, i
                    candidate_rows = []
                    candidate_start = -1
        else:
            if len(candidate_rows) >= 2:
                max_cols = max(len(r) for r in candidate_rows)
                norm = [r + [""] * (max_cols - len(r)) for r in candidate_rows]
                return norm, candidate_start, i
            candidate_rows = []
            candidate_start = -1

    if len(candidate_rows) >= 2:
        max_cols = max(len(r) for r in candidate_rows)
        norm = [r + [""] * (max_cols - len(r)) for r in candidate_rows]
        return norm, candidate_start, len(lines)

    # Strategy 3b: Borderless table with trailing numeric/currency tokens
    for i in range(len(lines)):
        header_line = lines[i].strip()
        if header_line.startswith(("- ", "* ", "• ", "▪ ")) or _is_heading_candidate(header_line)[0]:
            continue
        header_tokens = header_line.split()
        data_rows: list[list[str]] = []
        expected_trailing: Optional[int] = None
        data_end = i + 1
        for j in range(i + 1, len(lines)):
            row_str = lines[j].strip()
            if not row_str or row_str.startswith(("- ", "* ", "• ", "▪ ")) or _is_heading_candidate(row_str)[0]:
                break
            tokens = row_str.split()
            k = len(tokens) - 1
            trailing: list[str] = []
            while k >= 0 and NUMERIC_CELL_PATTERN.match(tokens[k]):
                trailing.insert(0, tokens[k])
                k -= 1
            if len(trailing) < 2:
                break
            if expected_trailing is None:
                expected_trailing = len(trailing)
            elif len(trailing) != expected_trailing:
                break
            leading = tokens[: k + 1]
            if not leading:
                break
            expected_leading = max(1, len(header_tokens) - expected_trailing)
            if expected_leading == 1:
                row_cols = [" ".join(leading)] + trailing
            elif len(leading) >= 2:
                if re.match(r"^[\w\d-]+$", leading[0]) and len(leading) > 2:
                    row_cols = [leading[0], " ".join(leading[1:])] + trailing
                else:
                    row_cols = [" ".join(leading[:-1]), leading[-1]] + trailing
            else:
                row_cols = leading + trailing
            data_rows.append(row_cols)
            data_end = j + 1

        if len(data_rows) >= 2 and expected_trailing is not None:
            num_cols = len(data_rows[0])
            diff = len(header_tokens) - num_cols
            if diff > 0:
                h_cols = [" ".join(header_tokens[: diff + 1])] + header_tokens[diff + 1 :]
                if len(h_cols) > num_cols:
                    h_cols = h_cols[: num_cols - expected_trailing] + header_tokens[-expected_trailing:]
            elif diff == 0:
                h_cols = header_tokens
            else:
                h_cols = header_tokens + [""] * (num_cols - len(header_tokens))
            return [h_cols] + data_rows, i, data_end

    return None


def _group_lines_into_paragraphs(lines: list[str]) -> list[str]:
    """Group visual lines into logical paragraphs, preserving explicit paragraph breaks.

    Joins wrapped lines within the same sentence while respecting headings,
    bullet points, captions, page numbers, and sentence termination.
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

        # Bullet points and numbered/lettered lists are always their own paragraph
        if stripped.startswith(("- ", "* ", "• ", "▪ ", "– ")) or re.match(r"^(\d+[\.\)]|\([a-zA-Z\d]+\)|[a-zA-Z][\.\)])\s+", stripped):
            if current_chunk:
                paragraphs.append(" ".join(current_chunk))
                current_chunk = []
            paragraphs.append(stripped)
            continue

        # Captions, table titles, page numbers, and headers/footers are independent paragraphs
        if re.match(r"^(Figure|Table|Page)\s+\d+", stripped, re.IGNORECASE) or re.match(r"^(Header|Footer):", stripped, re.IGNORECASE):
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
            # If previous line does NOT end with sentence/clause-ending punctuation, join
            elif not re.search(r"[.?!:;]$", prev):
                current_chunk.append(stripped)
            else:
                # Previous line was a complete sentence or clause. Start a new paragraph.
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
        ocr_language: Optional[str] = None,
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
            section.right_margin = Inches(1.0)

        total_chars = 0
        total_sanitized_chars = 0
        ocr_pages_count = 0
        tables_count = 0
        images_count = 0
        warnings: list[str] = []
        tmp_save = output_docx.with_suffix(f".tmp_{output_docx.name}")

        try:
            for page_idx in range(page_count):
                if cancel_check and cancel_check():
                    raise ConversionCancelledError(f"Reconstruction cancelled at page {page_idx + 1}.")

                page_num = page_idx + 1
                page = doc[page_idx]

                try:
                    # Orientation handling for rotated pages
                    page_rotation = page.get_rotation()
                    if page_rotation in (90, 270):
                        current_section = docx_doc.sections[-1]
                        current_section.orientation = WD_ORIENT.LANDSCAPE
                        w, h = current_section.page_width, current_section.page_height
                        if w < h:
                            current_section.page_width, current_section.page_height = h, w

                    # Text extraction with immediate XML sanitization
                    textpage = page.get_textpage()
                    raw_text = textpage.get_text_range() or ""
                    cleaned_text, s_cnt = sanitize_xml_text(
                        raw_text.replace("\r\n", "\n").replace("\r", "\n").strip()
                    )
                    total_sanitized_chars += s_cnt
                    char_count = len(cleaned_text)

                    has_images = False
                    has_paths = False
                    image_objects = []
                    text_font_sizes: list[float] = []

                    # Only scan page vector/image objects if needed for classification or extraction
                    if char_count < PdfInspector.SPARSE_TEXT_THRESHOLD or extract_images:
                        try:
                            for obj in page.get_objects():
                                obj_type = getattr(obj, "type", None)
                                tname = type(obj).__name__
                                if obj_type == 3 or tname == "PdfImage":
                                    has_images = True
                                    if extract_images and len(image_objects) < 25:
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

                    if should_ocr:
                        if cancel_check and cancel_check():
                            raise ConversionCancelledError(f"Reconstruction cancelled before OCR on page {page_num}.")

                        if RapidOcrEngine.is_available():
                            try:
                                img_arr = PdfPageRenderer.render_page(page, dpi=ocr_dpi)
                                ocr_res = RapidOcrEngine.process_image(
                                    img_arr, page_number=page_num, language=ocr_language
                                )
                                if ocr_res.text:
                                    ocr_applied = True
                                    ocr_pages_count += 1
                                    safe_ocr, s_ocr = sanitize_xml_text(ocr_res.text)
                                    total_sanitized_chars += s_ocr
                                    ocr_text = safe_ocr
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
                        if ocr_text:
                            ocr_lines = [l.strip() for l in ocr_text.splitlines() if l.strip()]
                            cls._render_text_lines(docx_doc, ocr_lines, median_font_size=14.0)
                            total_chars += len(ocr_text)
                    elif cleaned_text:
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

                        def _insert_images() -> None:
                            nonlocal images_count
                            if extract_images and image_objects:
                                for img_obj in list(image_objects):
                                    try:
                                        bmp = img_obj.get_bitmap()
                                        if bmp:
                                            pil_img = bmp.to_pil()
                                            w_px, h_px = pil_img.size
                                            if w_px >= 32 and h_px >= 32:
                                                buf = io.BytesIO()
                                                pil_img.save(buf, format="PNG")
                                                buf.seek(0)
                                                display_w = min(5.5, max(1.5, w_px / 150.0))
                                                docx_doc.add_picture(buf, width=Inches(display_w))
                                                images_count += 1
                                    except Exception as img_exc:
                                        log.debug("Failed to extract embedded image: %s", img_exc)
                                image_objects.clear()

                        caption_idx_before = next(
                            (i for i, l in enumerate(before_lines) if re.match(r"^Figure\s+\d+", l.strip(), re.IGNORECASE)),
                            None,
                        )
                        if caption_idx_before is not None:
                            cls._render_text_lines(docx_doc, before_lines[:caption_idx_before], median_font_size)
                            _insert_images()
                            cls._render_text_lines(docx_doc, before_lines[caption_idx_before:], median_font_size)
                        else:
                            cls._render_text_lines(docx_doc, before_lines, median_font_size)

                        if table_rows:
                            cls._add_table(docx_doc, table_rows)
                            tables_count += 1

                        caption_idx_after = next(
                            (i for i, l in enumerate(after_lines) if re.match(r"^Figure\s+\d+", l.strip(), re.IGNORECASE)),
                            None,
                        )
                        if caption_idx_after is not None:
                            cls._render_text_lines(docx_doc, after_lines[:caption_idx_after], median_font_size)
                            _insert_images()
                            cls._render_text_lines(docx_doc, after_lines[caption_idx_after:], median_font_size)
                        else:
                            cls._render_text_lines(docx_doc, after_lines, median_font_size)

                        if ocr_applied and ocr_text:
                            if not _is_duplicate_text(cleaned_text, ocr_text):
                                ocr_lines = [l.strip() for l in ocr_text.splitlines() if l.strip()]
                                cls._render_text_lines(docx_doc, ocr_lines, median_font_size=14.0)
                                total_chars += len(ocr_text)

                        total_chars += char_count
                        _insert_images()
                    else:
                        if classification is PageContentClassification.EMPTY_OR_UNKNOWN:
                            warnings.append(f"Page {page_num} is empty; no text or graphics detected.")
                        elif classification is PageContentClassification.IMAGE_LIKELY and not ocr_applied:
                            warnings.append(f"Page {page_num} contains images without extractable text.")

                    if page_idx < page_count - 1:
                        docx_doc.add_page_break()

                finally:
                    try:
                        textpage.close()
                    except Exception:
                        pass
                    try:
                        page.close()
                    except Exception:
                        pass

            if total_sanitized_chars > 0:
                warnings.append(
                    f"Sanitized {total_sanitized_chars} non-XML compatible control characters from extracted text."
                )

            # Save the document package atomically
            docx_doc.save(str(tmp_save))
            tmp_save.replace(output_docx)

        except ConversionCancelledError:
            raise
        except InvalidInputError:
            raise
        except Exception as exc:
            log.exception("DOCX document reconstruction failed: %s", exc)
            raise ConversionFailedError(f"DOCX reconstruction failed: {exc}") from exc
        finally:
            try:
                doc.close()
            except Exception:
                pass
            if tmp_save.exists():
                try:
                    tmp_save.unlink()
                except OSError:
                    pass

        return DocxReconstructionResult(
            page_count=page_count,
            total_characters=total_chars,
            warnings=tuple(warnings),
            ocr_applied_pages=ocr_pages_count,
            tables_count=tables_count,
            images_count=images_count,
            sanitized_characters_count=total_sanitized_chars,
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
                    safe_p, _ = sanitize_xml_text(para_text)
                    if safe_p.strip():
                        doc.add_paragraph(safe_p)
                pending_para_lines = []

        for line in lines:
            safe_line, _ = sanitize_xml_text(line.strip())
            if not safe_line:
                flush_paragraphs()
                continue

            is_hdg, level = _is_heading_candidate(safe_line, median_font_size=median_font_size)
            if is_hdg:
                flush_paragraphs()
                doc.add_heading(safe_line, level=level)
            elif safe_line.startswith(("- ", "* ", "• ", "▪ ", "– ")):
                flush_paragraphs()
                doc.add_paragraph(safe_line)
            else:
                pending_para_lines.append(safe_line)

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
                    val_str, _ = sanitize_xml_text(str(val).strip())
                    cell.text = val_str
                    if r_idx == 0:
                        for p in cell.paragraphs:
                            for r in p.runs:
                                r.font.bold = True
                    elif NUMERIC_CELL_PATTERN.match(val_str):
                        from docx.enum.text import WD_ALIGN_PARAGRAPH
                        for p in cell.paragraphs:
                            p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
