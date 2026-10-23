"""
localshift.planner — Conversion planning, capability discovery, and preflight validation.

This module provides:
- ConversionPlan generation explaining route support, options, and findings.
- Preflight validation API (point-in-time safety verification without executing).
- Public capability discovery functions.
- Option validation for adapter routes.

Planning and preflight NEVER:
- Execute conversions or invoke adapters.
- Create output or temporary files.
- Submit background jobs.
- Permanently reserve output paths.
- Mutate source files.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Optional, Sequence, Union

from .exceptions import UnsupportedFormatError
from .formats import input_format, normalize_format, sniff_format
from .models import (
    ConversionPlan,
    ConversionRequest,
    FindingSeverity,
    OptionSpec,
    ValidationFinding,
)
from .registry import AdapterRegistry, default_registry

log = logging.getLogger(__name__)

#: Default maximum input file size (aligned with converter).
MAX_INPUT_BYTES: int = 250 * 1024 * 1024  # 250 MiB


# ---------------------------------------------------------------------------
# Stable Finding Codes
# ---------------------------------------------------------------------------

class FindingCode:
    """Stable identifiers for validation findings."""
    SOURCE_NOT_FOUND = "SOURCE_NOT_FOUND"
    SOURCE_NOT_A_FILE = "SOURCE_NOT_A_FILE"
    SOURCE_SYMLINK_BROKEN = "SOURCE_SYMLINK_BROKEN"
    SOURCE_EMPTY = "SOURCE_EMPTY"
    SOURCE_TOO_LARGE = "SOURCE_TOO_LARGE"
    SOURCE_FORMAT_UNKNOWN = "SOURCE_FORMAT_UNKNOWN"
    SOURCE_FORMAT_UNSUPPORTED = "SOURCE_FORMAT_UNSUPPORTED"
    TARGET_FORMAT_INVALID = "TARGET_FORMAT_INVALID"
    ROUTE_UNSUPPORTED = "ROUTE_UNSUPPORTED"
    SAME_FORMAT_NO_OP = "SAME_FORMAT_NO_OP"
    DESTINATION_CONFLICT = "DESTINATION_CONFLICT"
    DESTINATION_DIR_INVALID = "DESTINATION_DIR_INVALID"
    UNKNOWN_OPTION = "UNKNOWN_OPTION"
    INVALID_OPTION_VALUE = "INVALID_OPTION_VALUE"
    ADAPTER_UNAVAILABLE = "ADAPTER_UNAVAILABLE"
    # Informational warnings
    TRANSPARENCY_LOSS_WARNING = "TRANSPARENCY_LOSS_WARNING"


# ---------------------------------------------------------------------------
# Capability Discovery API
# ---------------------------------------------------------------------------

def get_supported_source_formats(registry: Optional[AdapterRegistry] = None) -> list[str]:
    """Return a deterministic, sorted list of canonical formats accepted as input."""
    reg = registry or default_registry
    return sorted(reg.supported_source_formats())


def get_supported_target_formats(
    source_format: Optional[str] = None,
    registry: Optional[AdapterRegistry] = None,
) -> list[str]:
    """Return a deterministic, sorted list of canonical target formats.

    If *source_format* is given (as canonical key or alias), only target formats
    supported from that source format are returned.
    """
    reg = registry or default_registry
    if source_format is not None:
        try:
            norm_src = normalize_format(source_format)
        except (ValueError, UnsupportedFormatError):
            return []
        return sorted(reg.supported_target_formats(norm_src))
    return sorted(reg.supported_target_formats())


def get_supported_routes(registry: Optional[AdapterRegistry] = None) -> list[tuple[str, str]]:
    """Return a deterministic, sorted list of all supported (source, target) routes."""
    reg = registry or default_registry
    return sorted(reg.supported_routes())


def is_route_supported(
    source_format: str,
    target_format: str,
    registry: Optional[AdapterRegistry] = None,
) -> bool:
    """Return True if a directional conversion route is registered between the formats."""
    reg = registry or default_registry
    try:
        norm_src = normalize_format(source_format)
        norm_tgt = normalize_format(target_format)
    except (ValueError, UnsupportedFormatError):
        return False
    return reg.can_convert(norm_src, norm_tgt)


def get_applicable_options(
    source_format: str,
    target_format: str,
    registry: Optional[AdapterRegistry] = None,
) -> tuple[OptionSpec, ...]:
    """Return option specifications supported for the specified conversion route."""
    reg = registry or default_registry
    try:
        norm_src = normalize_format(source_format)
        norm_tgt = normalize_format(target_format)
    except (ValueError, UnsupportedFormatError):
        return ()
    return reg.get_supported_options(norm_src, norm_tgt)


def get_adapter_info(
    adapter_id: str,
    registry: Optional[AdapterRegistry] = None,
) -> Optional[dict[str, Any]]:
    """Return metadata dictionary for the specified adapter, or None if not found."""
    reg = registry or default_registry
    adapter = reg.get_adapter_by_id(adapter_id)
    if adapter is None:
        return None
    return {
        "adapter_id": adapter.adapter_id,
        "name": adapter.name,
        "supported_source_formats": sorted(adapter.supported_source_formats),
        "supported_target_formats": sorted(adapter.supported_target_formats),
        "supported_routes_count": len(adapter.supported_routes),
    }


# ---------------------------------------------------------------------------
# Option Validation Helper
# ---------------------------------------------------------------------------

def validate_conversion_options(
    options: dict[str, Any],
    applicable_options: Sequence[OptionSpec],
) -> list[ValidationFinding]:
    """Validate options dictionary against applicable OptionSpecs.

    Returns a list of ERROR findings for unknown or invalid option values.
    """
    findings: list[ValidationFinding] = []
    spec_map = {spec.name: spec for spec in applicable_options}

    for opt_name, opt_val in options.items():
        if opt_name not in spec_map:
            findings.append(
                ValidationFinding(
                    code=FindingCode.UNKNOWN_OPTION,
                    message=f"Unknown or unsupported option for this route: {opt_name!r}",
                    severity=FindingSeverity.ERROR,
                    field=f"options.{opt_name}",
                )
            )
            continue

        spec = spec_map[opt_name]

        # Route-specific validation for known options
        if opt_name == "jpeg_background":
            # Must be a 3-tuple / list of ints in range 0-255
            valid = False
            if isinstance(opt_val, (tuple, list)) and len(opt_val) == 3:
                if all(isinstance(c, int) and 0 <= c <= 255 for c in opt_val):
                    valid = True
            if not valid:
                findings.append(
                    ValidationFinding(
                        code=FindingCode.INVALID_OPTION_VALUE,
                        message=(
                            f"Option {opt_name!r} must be an RGB tuple of 3 integers "
                            f"(0-255), got {opt_val!r}"
                        ),
                        severity=FindingSeverity.ERROR,
                        field=f"options.{opt_name}",
                    )
                )

        if spec.choices is not None and opt_val not in spec.choices:
            findings.append(
                ValidationFinding(
                    code=FindingCode.INVALID_OPTION_VALUE,
                    message=f"Value {opt_val!r} for option {opt_name!r} is not in allowed choices: {spec.choices!r}",
                    severity=FindingSeverity.ERROR,
                    field=f"options.{opt_name}",
                )
            )

    return findings


# ---------------------------------------------------------------------------
# Preflight Validation API
# ---------------------------------------------------------------------------

def validate_preflight(
    request: ConversionRequest,
    *,
    registry: Optional[AdapterRegistry] = None,
    max_input_bytes: int = MAX_INPUT_BYTES,
) -> tuple[ValidationFinding, ...]:
    """Perform point-in-time preflight validation on a conversion request.

    This function NEVER executes the conversion, creates temporary files,
    or acquires permanent path reservations.

    Parameters
    ----------
    request:
        The conversion request to validate.
    registry:
        The adapter registry to validate against (defaults to default_registry).
    max_input_bytes:
        Configured input file size limit.

    Returns
    -------
    tuple[ValidationFinding, ...]
        List of findings. An empty list or findings with only WARNING severity
        indicate the request is ready for execution attempt.
    """
    reg = registry or default_registry
    findings: list[ValidationFinding] = []
    source = request.source

    # 1. Source existence and file type check
    source_exists = False
    source_is_file = False
    source_stat: Optional[os.stat_result] = None

    if not source.exists():
        findings.append(
            ValidationFinding(
                code=FindingCode.SOURCE_NOT_FOUND,
                message=f"Input file does not exist: {source}",
                severity=FindingSeverity.ERROR,
                field="source",
            )
        )
    else:
        source_exists = True
        if source.is_symlink():
            try:
                resolved = source.resolve()
                if not resolved.is_file():
                    findings.append(
                        ValidationFinding(
                            code=FindingCode.SOURCE_SYMLINK_BROKEN,
                            message=f"Symlink {source} does not resolve to a regular file.",
                            severity=FindingSeverity.ERROR,
                            field="source",
                        )
                    )
                else:
                    source_is_file = True
            except OSError as exc:
                findings.append(
                    ValidationFinding(
                        code=FindingCode.SOURCE_SYMLINK_BROKEN,
                        message=f"Failed to resolve symlink {source}: {exc}",
                        severity=FindingSeverity.ERROR,
                        field="source",
                    )
                )
        elif not source.is_file():
            findings.append(
                ValidationFinding(
                    code=FindingCode.SOURCE_NOT_A_FILE,
                    message=f"Input path is not a regular file: {source}",
                    severity=FindingSeverity.ERROR,
                    field="source",
                )
            )
        else:
            source_is_file = True

    # 2. Source file size
    if source_exists and source_is_file:
        try:
            source_stat = source.stat()
            size = source_stat.st_size
            if size == 0:
                findings.append(
                    ValidationFinding(
                        code=FindingCode.SOURCE_EMPTY,
                        message=f"Input file is empty (0 bytes): {source}",
                        severity=FindingSeverity.ERROR,
                        field="source",
                    )
                )
            elif size > max_input_bytes:
                limit_mib = max_input_bytes / (1024 * 1024)
                findings.append(
                    ValidationFinding(
                        code=FindingCode.SOURCE_TOO_LARGE,
                        message=(
                            f"Input file size ({size / (1024 * 1024):.1f} MiB) "
                            f"exceeds limit ({limit_mib:.0f} MiB)."
                        ),
                        severity=FindingSeverity.ERROR,
                        field="source",
                    )
                )
        except OSError as exc:
            findings.append(
                ValidationFinding(
                    code=FindingCode.SOURCE_NOT_A_FILE,
                    message=f"Could not stat input file {source}: {exc}",
                    severity=FindingSeverity.ERROR,
                    field="source",
                )
            )

    # 3. Source format identification
    src_key: Optional[str] = None
    if request.source_format is not None:
        try:
            src_key = normalize_format(request.source_format)
        except (ValueError, UnsupportedFormatError):
            findings.append(
                ValidationFinding(
                    code=FindingCode.SOURCE_FORMAT_UNSUPPORTED,
                    message=f"Declared source format {request.source_format!r} is unrecognised.",
                    severity=FindingSeverity.ERROR,
                    field="source_format",
                )
            )
    elif source_exists and source_is_file:
        # Sniff magic bytes first
        sniffed = sniff_format(source)
        if sniffed is not None:
            src_key = sniffed
        else:
            ext_based = input_format(source)
            if ext_based is not None:
                src_key = ext_based
            else:
                findings.append(
                    ValidationFinding(
                        code=FindingCode.SOURCE_FORMAT_UNKNOWN,
                        message=(
                            f"Cannot determine input format for {source.name!r}. "
                            "Unrecognised extension and content."
                        ),
                        severity=FindingSeverity.ERROR,
                        field="source",
                    )
                )
    else:
        # Fall back to extension for format guessing
        ext_based = input_format(source)
        if ext_based is not None:
            src_key = ext_based
        else:
            findings.append(
                ValidationFinding(
                    code=FindingCode.SOURCE_FORMAT_UNKNOWN,
                    message=f"Cannot determine input format for {source.name!r}.",
                    severity=FindingSeverity.ERROR,
                    field="source",
                )
            )

    # 4. Target format normalization
    target_key: Optional[str] = None
    try:
        target_key = normalize_format(request.target_format)
    except (ValueError, UnsupportedFormatError):
        findings.append(
            ValidationFinding(
                code=FindingCode.TARGET_FORMAT_INVALID,
                message=f"Target format specifier {request.target_format!r} is unrecognised.",
                severity=FindingSeverity.ERROR,
                field="target_format",
            )
        )

    # 5. Route validation & adapter selection
    applicable_options: tuple[OptionSpec, ...] = ()
    if src_key is not None and target_key is not None:
        if src_key == target_key:
            findings.append(
                ValidationFinding(
                    code=FindingCode.SAME_FORMAT_NO_OP,
                    message=(
                        f"Source and target formats are identical ({src_key!r}). "
                        "Same-format conversion is not supported."
                    ),
                    severity=FindingSeverity.ERROR,
                    field="target_format",
                )
            )
        elif not reg.can_convert(src_key, target_key):
            findings.append(
                ValidationFinding(
                    code=FindingCode.ROUTE_UNSUPPORTED,
                    message=f"No adapter supports route: {src_key!r} → {target_key!r}.",
                    severity=FindingSeverity.ERROR,
                    field="target_format",
                )
            )
        else:
            adapter = reg.get_adapter(src_key, target_key)
            if adapter is None:
                findings.append(
                    ValidationFinding(
                        code=FindingCode.ADAPTER_UNAVAILABLE,
                        message=f"No registered adapter instance for route: {src_key!r} → {target_key!r}.",
                        severity=FindingSeverity.ERROR,
                        field="target_format",
                    )
                )
            else:
                applicable_options = reg.get_supported_options(src_key, target_key)

    # 6. Option validation
    if request.options:
        opt_findings = validate_conversion_options(request.options, applicable_options)
        findings.extend(opt_findings)

    # 7. Destination folder & conflict checks
    dest_folder = request.output_dir if request.output_dir is not None else source.parent
    if dest_folder.exists() and not dest_folder.is_dir():
        findings.append(
            ValidationFinding(
                code=FindingCode.DESTINATION_DIR_INVALID,
                message=f"Destination output path exists and is not a directory: {dest_folder}",
                severity=FindingSeverity.ERROR,
                field="output_dir",
            )
        )

    # Destination collision check if target file would point to source
    if target_key is not None and source_exists:
        try:
            expected_target_file = dest_folder / f"{source.stem}.{target_key}"
            src_real = source.resolve()
            # If expected_target_file exists, check if it refers to source
            if expected_target_file.exists():
                tgt_real = expected_target_file.resolve()
                same = (src_real == tgt_real)
                if not same and os.name == "nt":
                    same = src_real.as_posix().lower() == tgt_real.as_posix().lower()
                if same:
                    findings.append(
                        ValidationFinding(
                            code=FindingCode.DESTINATION_CONFLICT,
                            message=f"Output destination resolves to the same physical file as source: {source}",
                            severity=FindingSeverity.ERROR,
                            field="output_dir",
                        )
                    )
        except OSError:
            pass

    return tuple(findings)


# ---------------------------------------------------------------------------
# Planning API
# ---------------------------------------------------------------------------

def plan_conversion(
    request_or_source: Union[ConversionRequest, Path, str],
    target_format: Optional[str] = None,
    *,
    output_dir: Optional[Union[Path, str]] = None,
    options: Optional[dict[str, Any]] = None,
    source_format: Optional[str] = None,
    registry: Optional[AdapterRegistry] = None,
    max_input_bytes: int = MAX_INPUT_BYTES,
) -> ConversionPlan:
    """Generate a structured ConversionPlan explaining route support, options, and findings.

    This function does NOT execute conversion, create files, or reserve paths.

    Parameters
    ----------
    request_or_source:
        A :class:`ConversionRequest` instance OR path to the source file.
    target_format:
        Target format specifier (if *request_or_source* is a Path or str).
    output_dir:
        Optional output directory.
    options:
        Optional adapter options dictionary.
    source_format:
        Optional explicit source format override.
    registry:
        The capability registry to query (defaults to default_registry).
    max_input_bytes:
        Configured input file size limit.

    Returns
    -------
    ConversionPlan
        Structured plan detailing normalized formats, route support, adapter,
        applicable options, validation findings, and execution readiness.
    """
    reg = registry or default_registry

    if isinstance(request_or_source, ConversionRequest):
        req = request_or_source
    else:
        if target_format is None:
            raise ValueError("target_format must be provided when passing a path as source.")
        req = ConversionRequest(
            source=Path(request_or_source),
            target_format=target_format,
            output_dir=Path(output_dir) if output_dir is not None else None,
            options=options or {},
            source_format=source_format,
        )

    findings = validate_preflight(req, registry=reg, max_input_bytes=max_input_bytes)

    # Normalize target format
    norm_tgt: Optional[str] = None
    try:
        norm_tgt = normalize_format(req.target_format)
    except (ValueError, UnsupportedFormatError):
        norm_tgt = None

    # Resolve normalized source format
    norm_src: Optional[str] = None
    if req.source_format is not None:
        try:
            norm_src = normalize_format(req.source_format)
        except (ValueError, UnsupportedFormatError):
            norm_src = None
    elif req.source.exists() and req.source.is_file():
        sniffed = sniff_format(req.source)
        norm_src = sniffed if sniffed is not None else input_format(req.source)
    else:
        norm_src = input_format(req.source)

    route_supported = False
    adapter_id: Optional[str] = None
    available_targets: tuple[str, ...] = ()
    applicable_opts: tuple[OptionSpec, ...] = ()

    if norm_src is not None:
        available_targets = tuple(sorted(reg.supported_target_formats(norm_src)))
        if norm_tgt is not None and reg.can_convert(norm_src, norm_tgt):
            route_supported = True
            adapter = reg.get_adapter(norm_src, norm_tgt)
            if adapter is not None:
                adapter_id = adapter.adapter_id
                applicable_opts = reg.get_supported_options(norm_src, norm_tgt)

    has_blocking_errors = any(f.blocks_execution for f in findings)
    is_ready = route_supported and not has_blocking_errors

    return ConversionPlan(
        source_format=norm_src,
        target_format=norm_tgt,
        route_supported=route_supported,
        adapter_id=adapter_id,
        available_target_formats=available_targets,
        applicable_options=applicable_opts,
        findings=findings,
        is_ready=is_ready,
    )


def plan_route(
    source_format: str,
    target_format: str,
    *,
    registry: Optional[AdapterRegistry] = None,
) -> ConversionPlan:
    """Generate a format-level ConversionPlan without requiring a physical source file.

    Useful for UI dropdown populations, route checking, and capability inspection.
    """
    reg = registry or default_registry
    findings: list[ValidationFinding] = []

    norm_src: Optional[str] = None
    try:
        norm_src = normalize_format(source_format)
    except (ValueError, UnsupportedFormatError):
        findings.append(
            ValidationFinding(
                code=FindingCode.SOURCE_FORMAT_UNSUPPORTED,
                message=f"Source format {source_format!r} is unrecognised.",
                severity=FindingSeverity.ERROR,
                field="source_format",
            )
        )

    norm_tgt: Optional[str] = None
    try:
        norm_tgt = normalize_format(target_format)
    except (ValueError, UnsupportedFormatError):
        findings.append(
            ValidationFinding(
                code=FindingCode.TARGET_FORMAT_INVALID,
                message=f"Target format {target_format!r} is unrecognised.",
                severity=FindingSeverity.ERROR,
                field="target_format",
            )
        )

    route_supported = False
    adapter_id: Optional[str] = None
    available_targets: tuple[str, ...] = ()
    applicable_opts: tuple[OptionSpec, ...] = ()

    if norm_src is not None:
        available_targets = tuple(sorted(reg.supported_target_formats(norm_src)))
        if norm_tgt is not None:
            if norm_src == norm_tgt:
                findings.append(
                    ValidationFinding(
                        code=FindingCode.SAME_FORMAT_NO_OP,
                        message=f"Source and target formats are identical ({norm_src!r}).",
                        severity=FindingSeverity.ERROR,
                        field="target_format",
                    )
                )
            elif not reg.can_convert(norm_src, norm_tgt):
                findings.append(
                    ValidationFinding(
                        code=FindingCode.ROUTE_UNSUPPORTED,
                        message=f"No registered adapter supports route: {norm_src!r} → {norm_tgt!r}.",
                        severity=FindingSeverity.ERROR,
                        field="target_format",
                    )
                )
            else:
                route_supported = True
                adapter = reg.get_adapter(norm_src, norm_tgt)
                if adapter is not None:
                    adapter_id = adapter.adapter_id
                    applicable_opts = reg.get_supported_options(norm_src, norm_tgt)

    is_ready = route_supported and not any(f.blocks_execution for f in findings)

    return ConversionPlan(
        source_format=norm_src,
        target_format=norm_tgt,
        route_supported=route_supported,
        adapter_id=adapter_id,
        available_target_formats=available_targets,
        applicable_options=applicable_opts,
        findings=tuple(findings),
        is_ready=is_ready,
    )
