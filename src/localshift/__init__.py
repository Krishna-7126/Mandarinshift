"""
LocalShift — offline-first Windows file converter.

Public API
----------
Callers (CLI, GUI, tests, future integrations) should import from this package
rather than from internal submodules where possible.

    from localshift import convert_image, ConversionError, ConversionResult
    from localshift import JobQueue, JobStatus, ConversionJob, JobResult
    from localshift import ProgressEvent, QueueFullError, JobNotFoundError
    from localshift.formats import SUPPORTED, route_supported, output_formats_for

Backend modules (``converter``, ``formats``, ``cli``, ``jobs``) have NO
dependency on PySide6.  Importing ``localshift`` or any backend module is
safe without a display server or GUI toolkit installed.
"""
from __future__ import annotations

__version__ = "0.3.0"
__all__ = [
    # Single-image conversion (original API — unchanged).
    "convert_image",
    "ConversionError",
    "ConversionResult",
    # Job management (new in 0.2.0; extended in 0.3.0).
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
    "__version__",
]

# Re-export primary backend interface.
from .converter import ConversionError, ConversionResult, convert_image

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
