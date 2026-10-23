"""
localshift.documents.pdf_inspector — Robust inspection, page metrics, and content classification for PDF documents.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)


class PageContentClassification(Enum):
    """Classification of content detected on a PDF page."""
    TEXT_PRESENT = "text_present"              # Page contains significant native extractable text
    IMAGE_LIKELY = "image_likely"              # Page contains little or no text; likely a scan or figure
    MIXED_OR_UNCERTAIN = "mixed_or_uncertain"  # Page contains sparse text or ambiguous mix of text & images
    EMPTY_OR_UNKNOWN = "empty_or_unknown"      # Page appears blank or has zero text and zero detected objects
    UNREADABLE = "unreadable"                  # Page could not be loaded or parsed


@dataclass(frozen=True)
class PageInspectionInfo:
    """Inspection metadata and heuristics for a single PDF page (1-based index)."""
    page_number: int
    width_points: float
    height_points: float
    rotation: int
    character_count: int
    classification: PageContentClassification
    extracted_text_preview: str
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class PdfInspectionReport:
    """Inspection and safety analysis report for an entire PDF document."""
    file_path: Path
    page_count: int
    is_encrypted: bool
    is_readable: bool
    pages: tuple[PageInspectionInfo, ...]
    total_characters: int
    warnings: tuple[str, ...] = ()
    error: Optional[str] = None

    @property
    def has_native_text(self) -> bool:
        """Return True if any page contains extractable native text."""
        return self.total_characters > 0 and any(
            p.classification in (PageContentClassification.TEXT_PRESENT, PageContentClassification.MIXED_OR_UNCERTAIN)
            for p in self.pages
        )

    @property
    def candidate_for_ocr(self) -> bool:
        """Return True if any page is classified as IMAGE_LIKELY or MIXED_OR_UNCERTAIN."""
        return any(
            p.classification in (PageContentClassification.IMAGE_LIKELY, PageContentClassification.MIXED_OR_UNCERTAIN)
            for p in self.pages
        )


class PdfInspector:
    """PDF inspection and heuristic classification engine using pypdfium2."""

    #: Threshold below which non-zero text is classified as sparse/mixed rather than full text.
    SPARSE_TEXT_THRESHOLD: int = 40

    @classmethod
    def inspect(cls, path: Path, *, password: Optional[str] = None) -> PdfInspectionReport:
        """Inspect *path* and return a structured :class:`PdfInspectionReport`."""
        import pypdfium2

        path = Path(path)
        warnings: list[str] = []

        if not path.exists():
            return PdfInspectionReport(
                file_path=path,
                page_count=0,
                is_encrypted=False,
                is_readable=False,
                pages=(),
                total_characters=0,
                error=f"File not found: {path}",
            )

        doc = None
        try:
            doc = pypdfium2.PdfDocument(path, password=password)
        except pypdfium2.PdfiumError as exc:
            err_msg = str(exc)
            is_encrypted = "password" in err_msg.lower()
            return PdfInspectionReport(
                file_path=path,
                page_count=0,
                is_encrypted=is_encrypted,
                is_readable=False,
                pages=(),
                total_characters=0,
                error=f"Password-protected PDF" if is_encrypted else f"Corrupt or unreadable PDF: {err_msg}",
            )
        except Exception as exc:
            return PdfInspectionReport(
                file_path=path,
                page_count=0,
                is_encrypted=False,
                is_readable=False,
                pages=(),
                total_characters=0,
                error=f"Failed to open PDF: {exc}",
            )

        page_infos: list[PageInspectionInfo] = []
        total_chars = 0

        try:
            page_count = len(doc)
            for page_idx in range(page_count):
                page_num = page_idx + 1
                page_warnings: list[str] = []
                try:
                    page = doc[page_idx]
                    width, height = page.get_size()
                    rotation = page.get_rotation()

                    textpage = page.get_textpage()
                    raw_text = textpage.get_text_range() or ""
                    cleaned_text = raw_text.strip()
                    char_count = len(cleaned_text)
                    total_chars += char_count

                    if rotation != 0:
                        page_warnings.append(f"Page has non-zero rotation: {rotation} degrees.")

                    # Classification heuristics
                    if char_count == 0:
                        classification = PageContentClassification.IMAGE_LIKELY
                        page_warnings.append("No native extractable text found on page.")
                    elif char_count < cls.SPARSE_TEXT_THRESHOLD:
                        classification = PageContentClassification.MIXED_OR_UNCERTAIN
                        page_warnings.append(
                            f"Sparse native text ({char_count} chars); may contain embedded graphics or OCR layers."
                        )
                    else:
                        classification = PageContentClassification.TEXT_PRESENT

                    preview = cleaned_text[:120].replace("\r", " ").replace("\n", " ")

                    page_infos.append(
                        PageInspectionInfo(
                            page_number=page_num,
                            width_points=float(width),
                            height_points=float(height),
                            rotation=int(rotation),
                            character_count=char_count,
                            classification=classification,
                            extracted_text_preview=preview,
                            warnings=tuple(page_warnings),
                        )
                    )
                except Exception as exc:
                    log.warning("Error inspecting page %d of %s: %s", page_num, path.name, exc)
                    page_infos.append(
                        PageInspectionInfo(
                            page_number=page_num,
                            width_points=0.0,
                            height_points=0.0,
                            rotation=0,
                            character_count=0,
                            classification=PageContentClassification.UNREADABLE,
                            extracted_text_preview="",
                            warnings=(f"Page unreadable: {exc}",),
                        )
                    )
        finally:
            if doc is not None:
                doc.close()

        if total_chars == 0 and len(page_infos) > 0:
            warnings.append("Document contains no extractable native text. OCR required for full conversion.")

        return PdfInspectionReport(
            file_path=path,
            page_count=len(page_infos),
            is_encrypted=False,
            is_readable=True,
            pages=tuple(page_infos),
            total_characters=total_chars,
            warnings=tuple(warnings),
        )
