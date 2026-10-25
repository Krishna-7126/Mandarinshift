"""
localshift.documents — PDF and document processing engine.
"""
from __future__ import annotations

from .adapter import PdfDocumentAdapter
from .docx_adapter import DocxToPdfAdapter
from .docx_renderer import DocxToPdfRenderer
from .pdf_image_exporter import PdfToImageExporter
from .image_to_pdf import ImageToPdfAdapter, ImageToPdfConverter
from .pdf_workbench import (
    PdfWorkbench,
    extract_pdf_pages,
    merge_pdfs,
    reorder_pdf_pages,
    rotate_pdf_pages,
    split_pdf,
)
from .ocr import (
    LanguagePackConfig,
    OcrPageResult,
    OcrTextBlock,
    RapidOcrEngine,
    normalize_ocr_text,
    preprocess_image_for_ocr,
    reconstruct_reading_order,
)
from .pdf_inspector import PageContentClassification, PageInspectionInfo, PdfInspectionReport, PdfInspector
from .renderer import PdfPageRenderer
from .text_extractor import DocumentExtractionResult, NativePdfTextExtractor, PageTextResult, PdfTextExtractor

__all__ = [
    "PdfDocumentAdapter",
    "DocxToPdfAdapter",
    "DocxToPdfRenderer",
    "PdfToImageExporter",
    "ImageToPdfAdapter",
    "ImageToPdfConverter",
    "PdfWorkbench",
    "merge_pdfs",
    "split_pdf",
    "extract_pdf_pages",
    "reorder_pdf_pages",
    "rotate_pdf_pages",
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
    "LanguagePackConfig",
    "OcrTextBlock",
    "OcrPageResult",
    "normalize_ocr_text",
    "preprocess_image_for_ocr",
    "reconstruct_reading_order",
]

