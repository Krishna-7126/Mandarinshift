"""
LocalShift — offline-first Windows file converter.

Public API
----------
Callers (CLI, GUI, tests, future integrations) should import from this package
rather than from internal submodules where possible.

    from localshift import (
        convert_image,
        convert_request,
        ConversionError,
        ConversionResult,
        ConversionRequest,
        ConversionContext,
        ConversionAdapter,
        AdapterRegistry,
        default_registry,
        PillowImageAdapter,
        JobQueue,
        JobStatus,
        ConversionJob,
        JobResult,
    )
    from localshift.formats import SUPPORTED, route_supported, output_formats_for

Backend modules have NO dependency on PySide6.
"""
from __future__ import annotations

__version__ = "0.5.0"
__all__ = [
    # Single-image conversion (original API — unchanged).
    "convert_image",
    "convert_request",
    "ConversionError",
    "ConversionResult",
    "ConversionRequest",
    "ConversionContext",
    # Error taxonomy
    "UnsupportedFormatError",
    "UnsupportedConversionError",
    "InvalidInputError",
    "InputTooLargeError",
    "DestinationConflictError",
    "AdapterUnavailableError",
    "ConversionFailedError",
    "ConversionCancelledError",
    "AdapterRegistrationError",
    # Adapter & Registry architecture (LS-BE-004)
    "ConversionAdapter",
    "AdapterRegistry",
    "default_registry",
    "PillowImageAdapter",
    "PdfDocumentAdapter",
    # Documents (LS-BE-006B)
    "PdfInspector",
    "PdfInspectionReport",
    "PageContentClassification",
    "NativePdfTextExtractor",
    # Job management
    "ConversionJob",
    "JobResult",
    "JobStatus",
    "JobQueue",
    "ProgressEvent",
    "QueueFullError",
    "JobNotFoundError",
    "BatchSubmission",
    "DEFAULT_MAX_COMPLETED",
    "DEFAULT_MAX_PENDING",
    "DEFAULT_WORKERS",
    # Planning & Preflight (LS-BE-005)
    "ConversionPlan",
    "ValidationFinding",
    "FindingSeverity",
    "OptionSpec",
    "FindingCode",
    "plan_conversion",
    "plan_route",
    "validate_preflight",
    "validate_conversion_options",
    # Capability Discovery (LS-BE-005)
    "get_supported_source_formats",
    "get_supported_target_formats",
    "get_supported_routes",
    "is_route_supported",
    "get_applicable_options",
    "get_adapter_info",
    "__version__",
]

# Re-export primary backend interface.
from .adapters.image import PillowImageAdapter
from .documents.adapter import PdfDocumentAdapter
from .documents.pdf_inspector import (
    PageContentClassification,
    PdfInspectionReport,
    PdfInspector,
)
from .documents.text_extractor import NativePdfTextExtractor
from .converter import (
    AdapterUnavailableError,
    ConversionCancelledError,
    ConversionContext,
    ConversionError,
    ConversionFailedError,
    ConversionRequest,
    ConversionResult,
    DestinationConflictError,
    InputTooLargeError,
    InvalidInputError,
    UnsupportedConversionError,
    UnsupportedFormatError,
    convert_image,
    convert_request,
)
from .exceptions import AdapterRegistrationError

# Re-export job management interface.
from .jobs import (
    BatchSubmission,
    ConversionJob,
    DEFAULT_MAX_COMPLETED,
    DEFAULT_MAX_PENDING,
    DEFAULT_WORKERS,
    JobNotFoundError,
    JobQueue,
    JobResult,
    JobStatus,
    ProgressEvent,
    QueueFullError,
)
from .models import (
    ConversionContext,
    ConversionPlan,
    ConversionRequest,
    ConversionResult,
    FindingSeverity,
    OptionSpec,
    ValidationFinding,
)
from .planner import (
    FindingCode,
    get_adapter_info,
    get_applicable_options,
    get_supported_routes,
    get_supported_source_formats,
    get_supported_target_formats,
    is_route_supported,
    plan_conversion,
    plan_route,
    validate_conversion_options,
    validate_preflight,
)
from .registry import AdapterRegistry, ConversionAdapter, default_registry
