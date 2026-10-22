"""
localshift.converter — Core conversion engine, coordination, and security boundary.

Responsibilities:
- Input validation (path safety, symlink traversal guards, size limits).
- Format detection and route validation via capability registry.
- Adapter dispatching.
- Process-level destination path reservation and collision prevention.
- Atomic output writing (temp-file creation + atomic rename).
- Result correctness verification before declaring success.
- Resource and temporary file cleanup on success or failure.

This module has NO dependency on PySide6 or the GUI layer.

Public API
----------
- ``ConversionError``          — base user-displayable conversion failure.
- ``UnsupportedFormatError``   — unknown format specifier.
- ``UnsupportedConversionError`` — route not supported by any adapter.
- ``InvalidInputError``        — missing, unreadable, or invalid input file.
- ``InputTooLargeError``       — input exceeds size limit.
- ``DestinationConflictError`` — source and destination point to same file.
- ``AdapterUnavailableError``  — required adapter not available.
- ``ConversionFailedError``    — adapter execution failure.
- ``ConversionCancelledError`` — conversion cancelled.
- ``ConversionRequest``        — structured request specification.
- ``ConversionContext``        — adapter execution context and security boundary.
- ``ConversionResult``         — structured conversion result value.
- ``convert_request()``        — primary request-based conversion entry point.
- ``convert_image()``          — legacy compatibility wrapper returning output Path.
- ``unique_output_path()``     — compute a non-colliding destination path.
- ``reserve_output_path()``    — atomically reserve a destination path.
- ``OutputReservation``        — context manager returned by reserve_output_path().
"""
from __future__ import annotations

import logging
import os
import tempfile
import threading
from pathlib import Path
from typing import Callable, Optional

from PIL import Image

from .exceptions import (
    AdapterUnavailableError,
    ConversionCancelledError,
    ConversionError,
    ConversionFailedError,
    DestinationConflictError,
    InputTooLargeError,
    InvalidInputError,
    UnsupportedConversionError,
    UnsupportedFormatError,
)
from .formats import PIL_FORMATS, input_format, normalize_format, sniff_format
from .models import ConversionContext, ConversionRequest, ConversionResult
from .registry import AdapterRegistry, default_registry

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Limits
# ---------------------------------------------------------------------------

#: Default maximum input file size. Matches README documentation.
MAX_INPUT_BYTES: int = 250 * 1024 * 1024  # 250 MiB


# ---------------------------------------------------------------------------
# Process-level output reservation lock & registry
# ---------------------------------------------------------------------------

# This lock serialises path reservation and registry updates for all threads
# in the same process. It ensures that concurrent conversions targeting the
# same output directory cannot pick the same destination filename.
_path_reservation_lock = threading.Lock()
_reserved_paths: set[str] = set()


def _normalize_reservation_path(path: Path) -> str:
    """Normalize a path to a canonical string for reservation tracking.

    On Windows (case-insensitive filesystem), paths are lowercased.
    """
    try:
        resolved = path.resolve()
        key = str(resolved)
    except OSError:
        key = str(path)
    return key.lower() if os.name == "nt" else key


def _reserve_path_locked(path: Path) -> None:
    """Reserve *path*. Caller must hold ``_path_reservation_lock``."""
    _reserved_paths.add(_normalize_reservation_path(path))


def _unreserve_path_locked(path: Path) -> None:
    """Unreserve *path*. Caller must hold ``_path_reservation_lock``."""
    _reserved_paths.discard(_normalize_reservation_path(path))


# ---------------------------------------------------------------------------
# Public Output Reservation Context Manager
# ---------------------------------------------------------------------------

class OutputReservation:
    """Context manager representing an active in-process output path reservation."""

    def __init__(self, path: Path):
        self.path = path
        self._released = False

    def release(self) -> None:
        """Release the path reservation."""
        if not self._released:
            with _path_reservation_lock:
                _unreserve_path_locked(self.path)
            self._released = True

    def __enter__(self) -> Path:
        return self.path

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.release()


# ---------------------------------------------------------------------------
# Output-path helpers
# ---------------------------------------------------------------------------

def unique_output_path(folder: Path, stem: str, extension: str) -> Path:
    """Return a path inside *folder* that does not yet exist and is not reserved.

    If ``<stem>.<extension>`` is free it is returned directly. Otherwise a
    numeric suffix ``(2)``, ``(3)``, … is appended until a free name is found.

    This function respects both files on disk and in-process reservations in
    ``_reserved_paths``.
    """
    candidate = folder / f"{stem}.{extension}"
    n = 2
    while candidate.exists() or _normalize_reservation_path(candidate) in _reserved_paths:
        candidate = folder / f"{stem} ({n}).{extension}"
        n += 1
    return candidate


def reserve_output_path(folder: Path, stem: str, extension: str) -> OutputReservation:
    """Atomically choose and reserve a unique destination path within *folder*.

    Returns an :class:`OutputReservation` context manager that holds the path
    reservation until exited or explicitly released.
    """
    with _path_reservation_lock:
        path = unique_output_path(folder, stem, extension)
        _reserve_path_locked(path)
        return OutputReservation(path)


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def _validate_source(source: Path, max_bytes: int) -> None:
    """Raise :class:`ConversionError` if *source* fails any safety check."""
    if not source.exists():
        raise InvalidInputError(f"Input file not found: {source}")
    if source.is_symlink():
        # Accept symlinks only if they resolve to a regular file.
        real = source.resolve()
        if not real.is_file():
            raise InvalidInputError(f"Symlink does not point to a regular file: {source}")
        log.debug("Source is a symlink; resolved to %s", real)
    if not source.is_file():
        raise InvalidInputError(f"Input path is not a regular file: {source}")
    size = source.stat().st_size
    if size > max_bytes:
        limit_mib = max_bytes / (1024 * 1024)
        raise InputTooLargeError(
            f"Input file is {size / (1024 * 1024):.1f} MiB, "
            f"which exceeds the {limit_mib:.0f} MiB limit."
        )


def _validate_no_source_dest_collision(source: Path, output: Path) -> None:
    """Raise :class:`DestinationConflictError` if *source* and *output* refer to the same file."""
    try:
        src_real = source.resolve()
        out_real = output.resolve()
        same = src_real == out_real
        if not same and os.name == "nt":
            same = src_real.as_posix().lower() == out_real.as_posix().lower()
    except OSError:
        same = str(source).lower() == str(output).lower()

    if same:
        raise DestinationConflictError(
            f"Output path is the same as the source file: {source}. "
            "LocalShift will not overwrite a source file."
        )


def _resolve_source_format(source: Path, declared_format: Optional[str]) -> str:
    """Return the canonical source format, preferring magic-byte detection."""
    if declared_format is not None:
        try:
            return normalize_format(declared_format)
        except ValueError as exc:
            raise UnsupportedFormatError(str(exc)) from exc

    # Prefer magic-byte detection.
    sniffed = sniff_format(source)
    if sniffed is not None:
        ext_based = input_format(source)
        if ext_based is not None and sniffed != ext_based:
            log.warning(
                "File %s: extension suggests %r but magic bytes indicate %r; "
                "using magic-byte result.",
                source.name, ext_based, sniffed,
            )
        return sniffed

    # Fall back to extension.
    ext_based = input_format(source)
    if ext_based is not None:
        log.debug("Using extension-based format detection for %s: %r", source.name, ext_based)
        return ext_based

    raise UnsupportedFormatError(
        f"Cannot determine input format for {source.name!r}. "
        "The file extension is unrecognised and the file content could not be identified."
    )


# ---------------------------------------------------------------------------
# Core conversion engine: convert_request
# ---------------------------------------------------------------------------

def convert_request(
    request: ConversionRequest,
    *,
    registry: Optional[AdapterRegistry] = None,
    max_input_bytes: int = MAX_INPUT_BYTES,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> ConversionResult:
    """Execute a structured conversion request using the adapter architecture.

    This function owns the security boundary:
    1. Validates input source existence, type, and size.
    2. Identifies and normalizes source and target formats.
    3. Finds the registered adapter capable of executing the route.
    4. Reserves a collision-free output path in the destination directory.
    5. Creates a secure temporary file for the adapter to write to.
    6. Invokes the adapter within a controlled :class:`ConversionContext`.
    7. Validates result correctness before atomically placing the output file.
    8. Guarantees cleanup of reservations and temporary files.

    Parameters
    ----------
    request:
        The conversion request specification.
    registry:
        The capability registry to dispatch through (defaults to :data:`default_registry`).
    max_input_bytes:
        Per-conversion file size limit.
    cancel_check:
        Optional callable returning True if cancellation has been requested.

    Returns
    -------
    ConversionResult
        Structured metadata for the successfully written output.

    Raises
    ------
    ConversionError (or specific subclasses: UnsupportedFormatError,
    UnsupportedConversionError, InvalidInputError, InputTooLargeError,
    DestinationConflictError, AdapterUnavailableError, ConversionFailedError,
    ConversionCancelledError).
    """
    reg = registry or default_registry
    source = request.source

    # Check cancellation before starting
    if cancel_check and cancel_check():
        raise ConversionCancelledError("Conversion was cancelled before processing started.")

    # 1. Input validation
    _validate_source(source, max_input_bytes)

    # 2. Format resolution
    try:
        target_key = normalize_format(request.target_format)
    except (ValueError, UnsupportedFormatError) as exc:
        raise UnsupportedFormatError(str(exc)) from exc

    src_key = _resolve_source_format(source, request.source_format)

    # 3. Route check & Adapter lookup
    if not reg.can_convert(src_key, target_key):
        raise UnsupportedConversionError(
            f"Unsupported conversion: {src_key!r} → {target_key!r}. "
            "These formats may be identical or not supported by any registered adapter."
        )

    adapter = reg.get_adapter(src_key, target_key)
    if adapter is None:
        raise AdapterUnavailableError(
            f"No adapter available for conversion route: {src_key!r} → {target_key!r}."
        )

    log.info(
        "convert_request: %s (%s) → %s via adapter %r (job_id=%s)",
        source.name, src_key, target_key, adapter.adapter_id, request.job_id,
    )

    # 4. Destination resolution & reservation
    folder = request.output_dir if request.output_dir is not None else source.parent
    folder.mkdir(parents=True, exist_ok=True)

    reservation = reserve_output_path(folder, source.stem, target_key)
    output = reservation.path
    tmp_path: Optional[Path] = None

    try:
        _validate_no_source_dest_collision(source, output)

        # 5. Create secure temporary file on same volume for atomic replacement
        fd, tmp_str = tempfile.mkstemp(
            suffix=f".{target_key}.tmp",
            dir=folder,
            prefix=f".localshift_{source.stem}_",
        )
        os.close(fd)
        tmp_path = Path(tmp_str)

        # 6. Create execution context
        context = ConversionContext(
            temp_output_path=tmp_path,
            target_format=target_key,
            max_input_bytes=max_input_bytes,
            _is_cancelled=cancel_check or (lambda: False),
        )

        # 7. Execute conversion via adapter
        adapter_req = ConversionRequest(
            source=source,
            target_format=target_key,
            output_dir=folder,
            options=request.options,
            job_id=request.job_id,
            source_format=src_key,
        )
        adapter_result = adapter.convert(adapter_req, context)

        # 8. Result correctness verification
        if not tmp_path.exists() or not tmp_path.is_file():
            raise ConversionFailedError(
                f"Adapter {adapter.adapter_id!r} completed without producing a valid output file."
            )

        try:
            in_size = source.stat().st_size
        except OSError:
            in_size = 0

        if in_size > 0 and tmp_path.stat().st_size == 0:
            raise ConversionFailedError(
                f"Adapter {adapter.adapter_id!r} completed without producing a valid output file (empty output)."
            )

        # 9. Atomic replace
        os.replace(tmp_path, output)
        tmp_path = None  # Successfully consumed

    except ConversionError:
        raise
    except Exception as exc:
        raise ConversionFailedError(f"Conversion failed: {exc}") from exc
    finally:
        # Release in-process reservation.
        reservation.release()

        # Clean up any leftover temporary file on failure.
        if tmp_path is not None and tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass

    try:
        input_bytes = source.stat().st_size
    except OSError:
        input_bytes = 0

    output_bytes = output.stat().st_size if output.exists() else 0

    log.info(
        "Conversion complete: %s → %s (%d bytes)",
        source.name, output.name, output_bytes,
    )

    return ConversionResult(
        output_path=output,
        source_format=src_key,
        target_format=target_key,
        input_bytes=input_bytes,
        output_bytes=output_bytes,
        adapter_id=adapter.adapter_id,
        warnings=adapter_result.warnings if adapter_result else (),
    )


# ---------------------------------------------------------------------------
# Backward-compatibility API: convert_image
# ---------------------------------------------------------------------------

def convert_image(
    source: Path | str,
    target: str,
    output_dir: Optional[Path | str] = None,
    *,
    jpeg_background: tuple[int, int, int] = (255, 255, 255),
    max_input_bytes: int = MAX_INPUT_BYTES,
    source_format: Optional[str] = None,
) -> Path:
    """Convert a single raster image and return the path to the output file.

    Maintains 100% backward compatibility with the LocalShift v0.1/v0.2/v0.3
    public API. Internally delegates through the adapter architecture.

    Parameters
    ----------
    source:
        Path to the input image file.
    target:
        Target format — accepts canonical keys (``"jpeg"``) or aliases (``"jpg"``).
    output_dir:
        Directory where the output file will be written. Defaults to source parent.
    jpeg_background:
        RGB tuple used to fill transparent regions when converting to JPEG.
    max_input_bytes:
        Maximum allowed input file size.
    source_format:
        Override source format detection. If None, magic bytes are used.

    Returns
    -------
    Path
        Path to the successfully written output file.
    """
    req = ConversionRequest(
        source=Path(source),
        target_format=target,
        output_dir=Path(output_dir) if output_dir is not None else None,
        options={"jpeg_background": jpeg_background},
        source_format=source_format,
    )
    result = convert_request(req, max_input_bytes=max_input_bytes)
    return result.output_path


# ---------------------------------------------------------------------------
# Backward-compatibility helper for mode coercion
# ---------------------------------------------------------------------------

def _coerce_mode(
    image: Image.Image,
    target_key: str,
    jpeg_background: tuple[int, int, int],
) -> Image.Image:
    """Compatibility wrapper delegating to PillowImageAdapter helper."""
    from .adapters.image import _coerce_image_mode
    return _coerce_image_mode(image, target_key, jpeg_background)
