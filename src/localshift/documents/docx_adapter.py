"""
localshift.documents.docx_adapter — DOCX to PDF Conversion Adapter.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from ..exceptions import (
    ConversionCancelledError,
    ConversionFailedError,
    InvalidInputError,
)
from ..models import ConversionContext, ConversionRequest, ConversionResult, OptionSpec
from .docx_renderer import DocxToPdfRenderer

log = logging.getLogger(__name__)


class DocxToPdfAdapter:
    """Conversion adapter for DOCX to PDF rendering via offline office backends."""

    adapter_id: str = "docx_to_pdf"
    name: str = "DOCX to PDF Conversion Adapter"

    def __init__(self) -> None:
        self._source_formats = frozenset({"docx"})
        self._target_formats = frozenset({"pdf"})
        self._routes = frozenset({("docx", "pdf")})

    @property
    def supported_source_formats(self) -> frozenset[str]:
        return self._source_formats

    @property
    def supported_target_formats(self) -> frozenset[str]:
        return self._target_formats

    @property
    def supported_routes(self) -> frozenset[tuple[str, str]]:
        return self._routes

    def is_available(self) -> bool:
        """Return True if at least one offline rendering backend is installed and functional."""
        return DocxToPdfRenderer.is_backend_available()

    def can_convert(self, source_format: str, target_format: str) -> bool:
        return (source_format, target_format) in self._routes and self.is_available()

    def get_supported_options(self, source_format: str, target_format: str) -> tuple[OptionSpec, ...]:
        """Return supported options for DOCX to PDF conversion."""
        if (source_format, target_format) == ("docx", "pdf"):
            return (
                OptionSpec(
                    name="renderer",
                    type_name="str",
                    default="auto",
                    choices=("auto", "libreoffice", "word_com"),
                    description="Offline rendering engine: 'auto' (detect LibreOffice or Word), 'libreoffice', or 'word_com'.",
                ),
                OptionSpec(
                    name="timeout",
                    type_name="int",
                    default=60,
                    description="Maximum rendering duration in seconds (5-300, default 60).",
                ),
            )
        return ()

    def convert(
        self,
        request: ConversionRequest,
        context: ConversionContext,
    ) -> ConversionResult:
        """Render DOCX to PDF directly into context.temp_output_path."""
        context.check_cancelled()

        if context.target_format != "pdf":
            raise ConversionFailedError(f"Unsupported target format for DocxToPdfAdapter: {context.target_format!r}")

        source_format = request.source_format or "docx"
        if source_format != "docx":
            raise ConversionFailedError(f"Unsupported source format for DocxToPdfAdapter: {source_format!r}")

        try:
            input_bytes = request.source.stat().st_size
        except OSError:
            input_bytes = 0

        # Extract options
        renderer_opt = request.options.get("renderer", "auto")
        timeout_opt = request.options.get("timeout", DocxToPdfRenderer.DEFAULT_TIMEOUT_SECONDS)

        # Cancel check adapter
        def cancel_check() -> bool:
            try:
                context.check_cancelled()
                return False
            except ConversionCancelledError:
                return True

        # Render document to secure temporary output path
        DocxToPdfRenderer.render_docx_to_pdf(
            request.source,
            context.temp_output_path,
            renderer=str(renderer_opt),
            timeout=int(timeout_opt),
            cancel_check=cancel_check,
        )

        context.check_cancelled()

        try:
            output_bytes = context.temp_output_path.stat().st_size
        except OSError:
            output_bytes = 0

        return ConversionResult(
            output_path=context.temp_output_path,
            source_format="docx",
            target_format="pdf",
            input_bytes=input_bytes,
            output_bytes=output_bytes,
            adapter_id=self.adapter_id,
            warnings=(),
        )
