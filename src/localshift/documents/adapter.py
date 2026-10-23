"""
localshift.documents.adapter — PDF Document Conversion Adapter supporting PDF to TXT.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from ..exceptions import ConversionCancelledError, ConversionFailedError, InvalidInputError
from ..models import ConversionContext, ConversionRequest, ConversionResult, OptionSpec
from .pdf_inspector import PageContentClassification
from .text_extractor import NativePdfTextExtractor

log = logging.getLogger(__name__)


class PdfDocumentAdapter:
    """Conversion adapter for PDF document processing (native text extraction to TXT)."""

    adapter_id: str = "pdf_native_text"
    name: str = "PDF Native Document Adapter"

    def __init__(self) -> None:
        self._source_formats = frozenset({"pdf"})
        self._target_formats = frozenset({"txt"})
        self._routes = frozenset({("pdf", "txt")})

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
            )
        return ()

    def convert(
        self,
        request: ConversionRequest,
        context: ConversionContext,
    ) -> ConversionResult:
        """Convert a PDF document into a plain-text document (.txt) at context.temp_output_path."""
        context.check_cancelled()

        if context.target_format != "txt":
            raise ConversionFailedError(f"Unsupported target format for PdfDocumentAdapter: {context.target_format!r}")

        page_sep = request.options.get("page_separator", "\n\n--- Page {page} ---\n\n")
        ocr_mode = str(request.options.get("ocr_mode", "auto"))
        try:
            ocr_dpi = int(request.options.get("ocr_dpi", 200))
        except (ValueError, TypeError):
            ocr_dpi = 200
        source_format = request.source_format or "pdf"

        try:
            input_bytes = request.source.stat().st_size
        except OSError:
            input_bytes = 0

        # Perform text extraction (with automatic or manual OCR routing) and cancellation callback
        try:
            extraction = NativePdfTextExtractor.extract(
                request.source,
                cancel_check=context.is_cancelled,
                ocr_mode=ocr_mode,
                ocr_dpi=ocr_dpi,
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
