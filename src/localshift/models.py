"""
localshift.models — Core data structures for conversion requests, context, and results.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
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
    #: Complete list of all output files written (e.g. for multipage document image exports).
    output_paths: tuple[Path, ...] = ()

    def __post_init__(self) -> None:
        if not self.output_paths and self.output_path:
            object.__setattr__(self, "output_paths", (self.output_path,))


# ---------------------------------------------------------------------------
# LS-BE-005 Planning, Preflight Validation & Capability Discovery Models
# ---------------------------------------------------------------------------

class FindingSeverity(Enum):
    """Severity classification for validation findings."""
    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True)
class ValidationFinding:
    """A structured finding emitted during preflight validation.

    Parameters
    ----------
    code:
        Stable finding code (e.g. ``"SOURCE_NOT_FOUND"``).
    message:
        Human-readable diagnostic description.
    severity:
        ``FindingSeverity.ERROR`` (blocks conversion) or ``FindingSeverity.WARNING``.
    field:
        Optional request field related to the finding (e.g. ``"source"``,
        ``"target_format"``, ``"options.jpeg_background"``).
    """

    code: str
    message: str
    severity: FindingSeverity = FindingSeverity.ERROR
    field: Optional[str] = None

    @property
    def blocks_execution(self) -> bool:
        """Return True if this finding blocks conversion execution."""
        return self.severity == FindingSeverity.ERROR


@dataclass(frozen=True)
class OptionSpec:
    """Specification of an adapter-supported conversion option.

    Parameters
    ----------
    name:
        Option key name as supplied in ``ConversionRequest.options``.
    type_name:
        Human-readable type description (e.g. ``"tuple[int, int, int]"``).
    default:
        Default value applied if the option is omitted.
    description:
        Explanation of the option and its effect on conversion output.
    choices:
        Optional finite tuple of allowed values, if constrained.
    """

    name: str
    type_name: str
    default: Any
    description: str
    choices: Optional[tuple[Any, ...]] = None


@dataclass(frozen=True)
class ConversionPlan:
    """Structured plan explaining route support, options, and preflight readiness.

    Parameters
    ----------
    source_format:
        Normalized canonical source format, or None if unidentifiable.
    target_format:
        Normalized canonical target format, or None if unrecognised.
    route_supported:
        True if the (source, target) route is supported by a registered adapter.
    adapter_id:
        Identifier of the adapter selected for this route, or None if unsupported.
    available_target_formats:
        Canonical target formats available from the resolved source format.
    applicable_options:
        Option specifications accepted by the selected adapter for this route.
    findings:
        All validation findings (errors and warnings) gathered during preflight.
    is_ready:
        True if the route is supported and there are no blocking ERROR findings.
    """

    source_format: Optional[str]
    target_format: Optional[str]
    route_supported: bool
    adapter_id: Optional[str]
    available_target_formats: tuple[str, ...]
    applicable_options: tuple[OptionSpec, ...]
    findings: tuple[ValidationFinding, ...]
    is_ready: bool

