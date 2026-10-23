"""
localshift.documents — PDF and document processing engine.
"""
from __future__ import annotations

from .adapter import PdfDocumentAdapter
from .ocr import OcrPageResult, OcrTextBlock, RapidOcrEngine, reconstruct_reading_order
from .pdf_inspector import PageContentClassification, PageInspectionInfo, PdfInspectionReport, PdfInspector
from .renderer import PdfPageRenderer
from .text_extractor import DocumentExtractionResult, NativePdfTextExtractor, PageTextResult, PdfTextExtractor

__all__ = [
    "PdfDocumentAdapter",
    "PdfInspector",
    "PdfInspectionReport",
    "PageInspectionInfo",
    "PageContentClassification",
    "NativePdfTextExtractor",
    "PdfTextExtractor",
    "DocumentExtractionResult",
    "PageTextResult",
    "PdfPageRenderer",
    "RapidOcrEngine",
    "OcrTextBlock",
    "OcrPageResult",
    "reconstruct_reading_order",
]
