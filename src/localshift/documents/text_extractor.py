"""
localshift.documents.text_extractor — Native text extraction, OCR routing, and structured page output.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from ..exceptions import ConversionCancelledError, ConversionFailedError, InvalidInputError
from .ocr import RapidOcrEngine
from .pdf_inspector import PageContentClassification, PdfInspectionReport, PdfInspector
from .renderer import PdfPageRenderer

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class PageTextResult:
    """Structured extraction result for a single PDF page (1-based)."""
    page_number: int
    text: str
    character_count: int
    classification: PageContentClassification
    warnings: tuple[str, ...] = ()
    ocr_applied: bool = False
    confidence: Optional[float] = None


@dataclass(frozen=True)
class DocumentExtractionResult:
    """Structured extraction result for an entire document."""
    file_path: Path
    page_count: int
    total_characters: int
    pages: tuple[PageTextResult, ...]
    warnings: tuple[str, ...] = ()
    ocr_pages_count: int = 0

    def to_plain_text(self, *, page_separator: str = "\n\n--- Page {page} ---\n\n") -> str:
        """Render all pages to a clean plain-text string with standardized page separators."""
        if self.total_characters == 0:
            return ""
        chunks = []
        for p in self.pages:
            sep = page_separator.format(page=p.page_number) if page_separator else ""
            chunks.append(f"{sep}{p.text}".strip() if not sep else f"{sep}{p.text}")
        return "\n".join(chunks).strip()


def _is_duplicate_text(native_str: str, ocr_str: str) -> bool:
    """Return True if native text is largely a duplicate or subset of OCR text."""
    norm_native = " ".join(native_str.lower().split())
    norm_ocr = " ".join(ocr_str.lower().split())
    if not norm_native or not norm_ocr:
        return False
    if norm_native in norm_ocr or norm_ocr in norm_native:
        return True
    native_words = norm_native.split()
    ocr_words = set(norm_ocr.split())
    if native_words:
        overlap = sum(1 for w in native_words if w in ocr_words)
        if (overlap / len(native_words)) >= 0.75:
            return True
    return False


class NativePdfTextExtractor:
    """Extracts text page-by-page from PDF files using pypdfium2 and local OCR."""

    #: Default limit on maximum pages processed to prevent resource exhaustion.
    MAX_PAGES_LIMIT: int = 2000

    @classmethod
    def extract(
        cls,
        path: Path,
        *,
        max_pages: int = MAX_PAGES_LIMIT,
        cancel_check: Optional[Callable[[], bool]] = None,
        ocr_mode: str = "native_only",
        ocr_dpi: int = PdfPageRenderer.DEFAULT_DPI,
    ) -> DocumentExtractionResult:
        """Extract text from *path* page by page with cooperative cancellation checks and OCR routing."""
        import pypdfium2

        path = Path(path)
        if not path.exists():
            raise InvalidInputError(f"Input file not found: {path}")

        ocr_mode_norm = ocr_mode.strip().lower()
        if ocr_mode_norm not in ("auto", "native_only", "force_ocr"):
            raise InvalidInputError(
                f"Invalid ocr_mode: {ocr_mode!r}. Must be 'auto', 'native_only', or 'force_ocr'."
            )

        if cancel_check and cancel_check():
            raise ConversionCancelledError("Extraction cancelled before starting.")

        doc = None
        try:
            doc = pypdfium2.PdfDocument(path)
        except pypdfium2.PdfiumError as exc:
            err_msg = str(exc)
            if "password" in err_msg.lower():
                raise InvalidInputError(f"Password-protected or encrypted PDF cannot be opened: {path.name}") from exc
            raise InvalidInputError(f"Corrupt or invalid PDF file: {exc}") from exc
        except Exception as exc:
            raise ConversionFailedError(f"Could not open PDF file: {exc}") from exc

        page_results: list[PageTextResult] = []
        total_chars = 0
        ocr_pages_count = 0
        doc_warnings: list[str] = []

        try:
            page_count = len(doc)
            if page_count > max_pages:
                raise InvalidInputError(
                    f"PDF document contains {page_count} pages, exceeding the limit of {max_pages} pages."
                )

            for page_idx in range(page_count):
                if cancel_check and cancel_check():
                    raise ConversionCancelledError(f"Extraction cancelled at page {page_idx + 1}.")

                page_num = page_idx + 1
                page_warnings: list[str] = []
                ocr_applied = False
                ocr_confidence: Optional[float] = None

                try:
                    page = doc[page_idx]
                    textpage = page.get_textpage()
                    raw_text = textpage.get_text_range() or ""
                    normalized_text = raw_text.replace("\r\n", "\n").replace("\r", "\n")
                    cleaned_text = normalized_text.strip()
                    char_count = len(cleaned_text)

                    has_images = False
                    has_paths = False
                    has_other_objects = False
                    try:
                        for obj in page.get_objects():
                            obj_type = getattr(obj, "type", None)
                            type_name = type(obj).__name__
                            if obj_type == 3 or type_name == "PdfImage":
                                has_images = True
                            elif obj_type == 2 or type_name == "PdfPath":
                                has_paths = True
                            elif obj_type != 1 and type_name != "PdfTextObj":
                                has_other_objects = True
                    except Exception:
                        pass

                    # Page classification heuristics
                    if char_count == 0:
                        if has_images:
                            classification = PageContentClassification.IMAGE_LIKELY
                            page_warnings.append("No native text extracted from page; page contains embedded image graphics.")
                        elif has_paths:
                            classification = PageContentClassification.MIXED_OR_UNCERTAIN
                            page_warnings.append("No native text extracted from page; page contains vector path elements.")
                        elif not has_other_objects:
                            classification = PageContentClassification.EMPTY_OR_UNKNOWN
                            page_warnings.append("Page appears to be empty; no text or graphics objects detected.")
                        else:
                            classification = PageContentClassification.IMAGE_LIKELY
                            page_warnings.append("No native text extracted from page.")
                    elif has_images:
                        classification = PageContentClassification.MIXED_OR_UNCERTAIN
                        page_warnings.append(f"Page contains both native text ({char_count} chars) and embedded graphics.")
                    elif char_count < PdfInspector.SPARSE_TEXT_THRESHOLD:
                        classification = PageContentClassification.MIXED_OR_UNCERTAIN
                        page_warnings.append(f"Sparse native text ({char_count} chars).")
                    else:
                        classification = PageContentClassification.TEXT_PRESENT

                    # OCR Routing Decision
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

                    if should_ocr:
                        if cancel_check and cancel_check():
                            raise ConversionCancelledError(f"Extraction cancelled before OCR on page {page_num}.")

                        if RapidOcrEngine.is_available():
                            try:
                                img_arr = PdfPageRenderer.render_page(page, dpi=ocr_dpi)
                                ocr_result = RapidOcrEngine.process_image(img_arr, page_number=page_num)

                                if ocr_result.text:
                                    if ocr_mode_norm == "force_ocr" or not cleaned_text:
                                        cleaned_text = ocr_result.text
                                    elif _is_duplicate_text(cleaned_text, ocr_result.text):
                                        # Prefer the longer/more complete text without duplicating lines
                                        cleaned_text = ocr_result.text if len(ocr_result.text) >= len(cleaned_text) else cleaned_text
                                    else:
                                        # Combine distinct native text and OCR text
                                        cleaned_text = f"{cleaned_text}\n\n{ocr_result.text}".strip()

                                    char_count = len(cleaned_text)
                                    ocr_applied = True
                                    ocr_confidence = ocr_result.mean_confidence
                                    ocr_pages_count += 1

                                for w in ocr_result.warnings:
                                    page_warnings.append(w)
                            except ConversionCancelledError:
                                raise
                            except Exception as ocr_exc:
                                log.warning("OCR failed on page %d: %s", page_num, ocr_exc)
                                page_warnings.append(f"OCR processing failed on page {page_num}: {ocr_exc}")
                        else:
                            page_warnings.append("Page appears to be a scan, but OCR engine is unavailable.")

                    total_chars += char_count
                    page_results.append(
                        PageTextResult(
                            page_number=page_num,
                            text=cleaned_text,
                            character_count=char_count,
                            classification=classification,
                            warnings=tuple(page_warnings),
                            ocr_applied=ocr_applied,
                            confidence=ocr_confidence,
                        )
                    )
                except ConversionCancelledError:
                    raise
                except Exception as exc:
                    log.error("Failed to extract text from page %d: %s", page_num, exc)
                    page_results.append(
                        PageTextResult(
                            page_number=page_num,
                            text="",
                            character_count=0,
                            classification=PageContentClassification.UNREADABLE,
                            warnings=(f"Page text extraction failed: {exc}",),
                        )
                    )
        finally:
            if doc is not None:
                doc.close()

        if ocr_pages_count > 0:
            doc_warnings.append(f"Scanned page: OCR applied to {ocr_pages_count} of {len(page_results)} page(s).")
        elif total_chars == 0 and len(page_results) > 0:
            doc_warnings.append("No extractable native text found across any pages. File may be an image scan.")

        return DocumentExtractionResult(
            file_path=path,
            page_count=len(page_results),
            total_characters=total_chars,
            pages=tuple(page_results),
            warnings=tuple(doc_warnings),
            ocr_pages_count=ocr_pages_count,
        )


# Backward-compatible alias
PdfTextExtractor = NativePdfTextExtractor
