"""
localshift.documents.adapter — PDF Document Conversion Adapter supporting PDF to TXT.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from ..exceptions import (
    ConversionCancelledError,
    ConversionFailedError,
    InputTooLargeError,
    InvalidInputError,
)
from ..models import ConversionContext, ConversionRequest, ConversionResult, OptionSpec
from .docx_builder import PdfToDocxReconstructor
from .pdf_image_exporter import PdfToImageExporter
from .pdf_inspector import PageContentClassification
from .text_extractor import NativePdfTextExtractor

log = logging.getLogger(__name__)


class PdfDocumentAdapter:
    """Conversion adapter for PDF document processing (TXT text extraction, DOCX reconstruction, and PNG/JPEG raster export)."""

    adapter_id: str = "pdf_native_text"
    name: str = "PDF Document Adapter"

    def __init__(self) -> None:
        self._source_formats = frozenset({"pdf"})
        self._target_formats = frozenset({"txt", "docx", "png", "jpeg"})
        self._routes = frozenset({
            ("pdf", "txt"),
            ("pdf", "docx"),
            ("pdf", "png"),
            ("pdf", "jpeg"),
        })

    @property
    def supported_source_formats(self) -> frozenset[str]:
        return self._source_formats

    @property
    def supported_target_formats(self) -> frozenset[str]:
        return self._target_formats

    @property
    def supported_routes(self) -> frozenset[tuple[str, str]]:
        return self._routes

    def can_convert(self, source_format: str, target_format: str) -> bool:
        return (source_format, target_format) in self._routes

    def get_supported_options(self, source_format: str, target_format: str) -> tuple[OptionSpec, ...]:
        """Return supported options for PDF conversions."""
        if (source_format, target_format) == ("pdf", "txt"):
            return (
                OptionSpec(
                    name="page_separator",
                    type_name="str",
                    default="\n\n--- Page {page} ---\n\n",
                    description="Separator string placed between consecutive pages in output text.",
                ),
                OptionSpec(
                    name="ocr_mode",
                    type_name="str",
                    default="auto",
                    choices=("auto", "native_only", "force_ocr"),
                    description="OCR strategy: 'auto' (OCR scanned/sparse pages), 'native_only' (fast digital text), 'force_ocr' (rasterize all pages).",
                ),
                OptionSpec(
                    name="ocr_dpi",
                    type_name="int",
                    default=200,
                    description="DPI resolution for OCR rasterization (72-400, default 200).",
                ),
                OptionSpec(
                    name="ocr_language",
                    type_name="str",
                    default="auto",
                    description="Target OCR language: 'auto'/'en'/'ch' (bundled) or registered language pack (e.g. 'hi').",
                ),
            )
        elif (source_format, target_format) == ("pdf", "docx"):
            return (
                OptionSpec(
                    name="ocr_mode",
                    type_name="str",
                    default="auto",
                    choices=("auto", "native_only", "force_ocr"),
                    description="OCR strategy: 'auto' (OCR scanned/sparse pages), 'native_only' (fast digital text), 'force_ocr' (rasterize all pages).",
                ),
                OptionSpec(
                    name="ocr_dpi",
                    type_name="int",
                    default=200,
                    description="DPI resolution for OCR rasterization (72-400, default 200).",
                ),
                OptionSpec(
                    name="ocr_language",
                    type_name="str",
                    default="auto",
                    description="Target OCR language: 'auto'/'en'/'ch' (bundled) or registered language pack (e.g. 'hi').",
                ),
                OptionSpec(
                    name="extract_images",
                    type_name="bool",
                    default=True,
                    description="Extract and embed illustrations and graphics into the Word document.",
                ),
            )
        elif (source_format, target_format) == ("pdf", "png"):
            return (
                OptionSpec(
                    name="dpi",
                    type_name="int",
                    default=200,
                    description="Resolution in DPI for rasterizing PDF pages (72-400, default 200).",
                ),
                OptionSpec(
                    name="pages",
                    type_name="str",
                    default="all",
                    description="Page selection specification: 'all', single page ('1'), range ('1-3'), or comma list ('1,3,5'). 1-based indexing.",
                ),
                OptionSpec(
                    name="output_pattern",
                    type_name="str",
                    default="{stem}_page_{page}.{ext}",
                    description="Naming pattern for exported page images. Placeholders: {stem}, {page}, {page_count}, {ext}.",
                ),
            )
        elif (source_format, target_format) == ("pdf", "jpeg"):
            return (
                OptionSpec(
                    name="dpi",
                    type_name="int",
                    default=200,
                    description="Resolution in DPI for rasterizing PDF pages (72-400, default 200).",
                ),
                OptionSpec(
                    name="pages",
                    type_name="str",
                    default="all",
                    description="Page selection specification: 'all', single page ('1'), range ('1-3'), or comma list ('1,3,5'). 1-based indexing.",
                ),
                OptionSpec(
                    name="output_pattern",
                    type_name="str",
                    default="{stem}_page_{page}.{ext}",
                    description="Naming pattern for exported page images. Placeholders: {stem}, {page}, {page_count}, {ext}.",
                ),
                OptionSpec(
                    name="quality",
                    type_name="int",
                    default=90,
                    description="JPEG compression quality from 1 to 100 (default 90).",
                ),
                OptionSpec(
                    name="jpeg_background",
                    type_name="tuple[int, int, int]",
                    default=(255, 255, 255),
                    description="Background color used when compositing or rendering PDF pages to JPEG.",
                ),
            )
        elif (source_format, target_format) in (("pdf", "webp"), ("pdf", "tiff")):
            return (
                OptionSpec(
                    name="dpi",
                    type_name="int",
                    default=200,
                    description="Resolution in DPI for rasterizing PDF pages (72-400, default 200).",
                ),
                OptionSpec(
                    name="pages",
                    type_name="str",
                    default="all",
                    description="Page selection specification: 'all', single page ('1'), range ('1-3'), or comma list ('1,3,5'). 1-based indexing.",
                ),
                OptionSpec(
                    name="output_pattern",
                    type_name="str",
                    default="{stem}_page_{page}.{ext}",
                    description="Naming pattern for exported page images. Placeholders: {stem}, {page}, {page_count}, {ext}.",
                ),
            )
        return ()

    def convert(
        self,
        request: ConversionRequest,
        context: ConversionContext,
    ) -> ConversionResult:
        """Convert a PDF document into TXT, DOCX, PNG, JPEG, WebP, or TIFF."""
        context.check_cancelled()

        if context.target_format not in ("txt", "docx", "png", "jpeg", "webp", "tiff"):
            raise ConversionFailedError(f"Unsupported target format for PdfDocumentAdapter: {context.target_format!r}")

        source_format = request.source_format or "pdf"

        try:
            input_bytes = request.source.stat().st_size
        except OSError:
            input_bytes = 0

        if context.max_input_bytes and input_bytes > context.max_input_bytes:
            raise InputTooLargeError(
                f"PDF input size ({input_bytes} bytes) exceeds limit of {context.max_input_bytes} bytes."
            )

        # Route: PDF -> PNG / JPEG / WebP / TIFF raster image export
        if context.target_format in ("png", "jpeg", "webp", "tiff"):
            folder = request.output_dir if request.output_dir is not None else request.source.parent
            output_paths, output_bytes = PdfToImageExporter.export_pdf_to_images(
                request.source,
                folder,
                context.target_format,
                options=request.options,
                max_input_bytes=context.max_input_bytes,
                cancel_check=context.is_cancelled,
            )
            context.check_cancelled()
            return ConversionResult(
                output_path=output_paths[0],
                source_format=source_format,
                target_format=context.target_format,
                input_bytes=input_bytes,
                output_bytes=output_bytes,
                adapter_id=self.adapter_id,
                warnings=(),
                output_paths=output_paths,
            )

        ocr_mode = str(request.options.get("ocr_mode", "auto"))
        try:
            ocr_dpi = int(request.options.get("ocr_dpi", 200))
        except (ValueError, TypeError):
            ocr_dpi = 200
        ocr_language = request.options.get("ocr_language") or request.options.get("language")

        if context.target_format == "docx":
            extract_images = bool(request.options.get("extract_images", True))
            recon_res = PdfToDocxReconstructor.reconstruct(
                request.source,
                context.temp_output_path,
                cancel_check=context.is_cancelled,
                ocr_mode=ocr_mode,
                ocr_dpi=ocr_dpi,
                extract_images=extract_images,
                max_input_bytes=context.max_input_bytes,
                ocr_language=ocr_language,
            )
            context.check_cancelled()
            try:
                output_bytes = context.temp_output_path.stat().st_size
            except OSError:
                output_bytes = 0

            return ConversionResult(
                output_path=context.temp_output_path,
                source_format=source_format,
                target_format=context.target_format,
                input_bytes=input_bytes,
                output_bytes=output_bytes,
                adapter_id=self.adapter_id,
                warnings=recon_res.warnings,
            )

        page_sep = request.options.get("page_separator", "\n\n--- Page {page} ---\n\n")

        # Perform text extraction (with automatic or manual OCR routing) and cancellation callback
        try:
            extraction = NativePdfTextExtractor.extract(
                request.source,
                cancel_check=context.is_cancelled,
                ocr_mode=ocr_mode,
                ocr_dpi=ocr_dpi,
                ocr_language=ocr_language,
            )
        except ConversionCancelledError:
            raise
        except InvalidInputError:
            raise
        except Exception as exc:
            log.exception("PDF text extraction failed for %s", request.source.name)
            raise ConversionFailedError(f"Could not extract text from PDF: {exc}") from exc

        context.check_cancelled()

        unreadable_pages = [
            str(page.page_number)
            for page in extraction.pages
            if page.classification is PageContentClassification.UNREADABLE
        ]
        if unreadable_pages:
            raise ConversionFailedError(
                f"Could not extract text from PDF page(s): {', '.join(unreadable_pages)}."
            )

        try:
            full_text = extraction.to_plain_text(page_separator=page_sep)
            # Write plain text as UTF-8
            context.temp_output_path.write_text(full_text, encoding="utf-8")
        except Exception as exc:
            raise ConversionFailedError(f"Failed to write output text file: {exc}") from exc

        try:
            output_bytes = context.temp_output_path.stat().st_size
        except OSError:
            output_bytes = 0

        return ConversionResult(
            output_path=context.temp_output_path,
            source_format=source_format,
            target_format=context.target_format,
            input_bytes=input_bytes,
            output_bytes=output_bytes,
            adapter_id=self.adapter_id,
            warnings=extraction.warnings,
        )
