"""
localshift.documents — PDF and document processing engine.
"""
from __future__ import annotations

from .adapter import PdfDocumentAdapter
from .pdf_inspector import PageContentClassification, PageInspectionInfo, PdfInspectionReport, PdfInspector
from .text_extractor import DocumentExtractionResult, NativePdfTextExtractor, PageTextResult

__all__ = [
    "PdfDocumentAdapter",
    "PdfInspector",
    "PdfInspectionReport",
    "PageInspectionInfo",
    "PageContentClassification",
    "NativePdfTextExtractor",
    "DocumentExtractionResult",
    "PageTextResult",
]
