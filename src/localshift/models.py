"""
localshift.models — Core data structures for conversion requests, context, and results.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from .exceptions import ConversionCancelledError


@dataclass(frozen=True)
class ConversionRequest:
    """Immutable specification of a conversion job request.

    Parameters
    ----------
    source:
        Absolute or relative path to the input file.
    target_format:
        Target format specifier (canonical key or alias, e.g. ``"jpeg"`` or ``"jpg"``).
    output_dir:
        Target directory for the converted output. If ``None``, defaults to the
        source file's directory.
    options:
        Adapter-specific options dictionary (e.g. ``{"jpeg_background": (255, 255, 255)}``).
    job_id:
        Optional tracking identifier for queue or logging context.
    source_format:
        Optional explicit source format override. If ``None``, the format is
        inferred from magic bytes or extension.
    """

    source: Path
    target_format: str
    output_dir: Optional[Path] = None
    options: dict[str, Any] = field(default_factory=dict)
    job_id: Optional[str] = None
    source_format: Optional[str] = None

    def __post_init__(self) -> None:
        if not isinstance(self.source, Path):
            object.__setattr__(self, "source", Path(self.source))
        if self.output_dir is not None and not isinstance(self.output_dir, Path):
            object.__setattr__(self, "output_dir", Path(self.output_dir))


@dataclass(frozen=True)
class ConversionContext:
    """Execution context and security boundary provided to adapters by the core engine.

    The core engine retains exclusive ownership of:
    - Path validation and traversal guards
    - Output filename selection and in-process reservations
    - Temporary file creation and atomic replacement
    - Post-execution output verification

    The adapter writes only to ``temp_output_path`` and queries ``is_cancelled()``
    for cooperative cancellation.
    """

    temp_output_path: Path
    target_format: str
    max_input_bytes: int
    _is_cancelled: Callable[[], bool] = field(default=lambda: False)

    def is_cancelled(self) -> bool:
        """Return True if cancellation has been requested for this conversion."""
        try:
            return self._is_cancelled()
        except Exception:
            return False

    def check_cancelled(self) -> None:
        """Raise :class:`ConversionCancelledError` if cancellation has been requested."""
        if self.is_cancelled():
            raise ConversionCancelledError("Conversion was cancelled by user request.")


@dataclass(frozen=True)
class ConversionResult:
    """Structured result returned by a successful conversion."""

    #: Resolved path to the final output file written to disk.
    output_path: Path
    #: Canonical source format key (e.g. ``"png"``).
    source_format: str
    #: Canonical target format key (e.g. ``"jpeg"``).
    target_format: str
    #: Input file size in bytes.
    input_bytes: int
    #: Output file size in bytes.
    output_bytes: int
    #: Identifier of the adapter that executed the conversion.
    adapter_id: str = "pillow_raster"
    #: Diagnostic warnings emitted during conversion, if any.
    warnings: tuple[str, ...] = ()
