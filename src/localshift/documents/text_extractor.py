"""
localshift.documents.text_extractor — Native text extraction and structured page output.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from ..exceptions import ConversionCancelledError, ConversionFailedError, InvalidInputError
from .pdf_inspector import PageContentClassification, PdfInspectionReport, PdfInspector

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class PageTextResult:
    """Structured extraction result for a single PDF page (1-based)."""
    page_number: int
    text: str
    character_count: int
    classification: PageContentClassification
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class DocumentExtractionResult:
    """Structured extraction result for an entire document."""
    file_path: Path
    page_count: int
    total_characters: int
    pages: tuple[PageTextResult, ...]
    warnings: tuple[str, ...] = ()

    def to_plain_text(self, *, page_separator: str = "\n\n--- Page {page} ---\n\n") -> str:
        """Render all pages to a clean plain-text string with standardized page separators."""
        chunks = []
        for p in self.pages:
            sep = page_separator.format(page=p.page_number) if page_separator else ""
            chunks.append(f"{sep}{p.text}".strip() if not sep else f"{sep}{p.text}")
        return "\n".join(chunks).strip()


class NativePdfTextExtractor:
    """Extracts native text page-by-page from PDF files using pypdfium2."""

    #: Default limit on maximum pages processed to prevent resource exhaustion.
    MAX_PAGES_LIMIT: int = 2000

    @classmethod
    def extract(
        cls,
        path: Path,
        *,
        max_pages: int = MAX_PAGES_LIMIT,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> DocumentExtractionResult:
        """Extract native text from *path* page by page with cooperative cancellation checks."""
        import pypdfium2

        path = Path(path)
        if not path.exists():
            raise InvalidInputError(f"Input file not found: {path}")

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

                try:
                    page = doc[page_idx]
                    textpage = page.get_textpage()
                    # Extract full page text range
                    raw_text = textpage.get_text_range() or ""
                    # Standardize carriage returns to standard newlines
                    normalized_text = raw_text.replace("\r\n", "\n").replace("\r", "\n")
                    cleaned_text = normalized_text.strip()
                    char_count = len(cleaned_text)
                    total_chars += char_count

                    if char_count == 0:
                        classification = PageContentClassification.IMAGE_LIKELY
                        page_warnings.append("No native text extracted from page.")
                    elif char_count < PdfInspector.SPARSE_TEXT_THRESHOLD:
                        classification = PageContentClassification.MIXED_OR_UNCERTAIN
                        page_warnings.append(f"Sparse native text ({char_count} chars).")
                    else:
                        classification = PageContentClassification.TEXT_PRESENT

                    page_results.append(
                        PageTextResult(
                            page_number=page_num,
                            text=cleaned_text,
                            character_count=char_count,
                            classification=classification,
                            warnings=tuple(page_warnings),
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

        if total_chars == 0 and len(page_results) > 0:
            doc_warnings.append("No extractable native text found across any pages. File may be an image scan.")

        return DocumentExtractionResult(
            file_path=path,
            page_count=len(page_results),
            total_characters=total_chars,
            pages=tuple(page_results),
            warnings=tuple(doc_warnings),
        )
