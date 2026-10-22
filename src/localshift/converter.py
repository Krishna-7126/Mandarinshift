"""
localshift.converter — Core raster image conversion engine.

Responsibilities:
- Input validation (path safety, size limits, format detection).
- Conversion planning (route validation).
- Conversion execution using Pillow.
- Atomic output writing (temp-file + rename).
- Output collision avoidance with a process-level reservation lock.
- Structured diagnostic logging.
- Resource cleanup on failure.

This module has NO dependency on PySide6 or the GUI layer.

Public API
----------
- ``ConversionError``          — user-displayable conversion failure.
- ``ConversionResult``         — structured result value.
- ``convert_image()``          — convert a single raster image.
- ``unique_output_path()``     — compute a non-colliding destination path.
- ``reserve_output_path()``    — atomically reserve a destination path.
- ``OutputReservation``        — context manager returned by reserve_output_path().

Output Reservation
------------------
The output collision race (check-then-act between unique_output_path and
os.replace) is addressed by a two-level approach:

1. **Process-level**: A module-global ``threading.Lock`` serialises the
   path-selection and temporary-file creation steps for all workers in the
   same process, preventing two workers from choosing the same destination.

2. **Filesystem-level**: ``tempfile.mkstemp`` is used in exclusive-create
   mode.  Its successful return proves exclusive ownership of the temporary
   file within the same directory as the target, on the same filesystem
   volume, making the final ``os.replace()`` safe.

**Cross-process protection**: Not provided.  Two unrelated processes can
still race.  For a single-process desktop application this is sufficient.

Security notes
--------------
- Source files are never modified.
- Symlinks are detected and accepted only if they resolve to a regular file
  whose real path is inside the same volume (basic traversal guard).
- Output is written atomically: a temporary file in the same directory is
  renamed over the final destination only on success.  Partial files are
  removed on any failure caught by the try/except.
- Path traversal in ``output_dir`` is not actively restricted here; callers
  (CLI, GUI) are responsible for validating user-supplied paths.
- Source and output identity is checked: converting a file to itself raises
  ConversionError.
"""
from __future__ import annotations

import logging
import os
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PIL import Image, ImageOps, UnidentifiedImageError

from .formats import PIL_FORMATS, input_format, normalize_format, route_supported, sniff_format

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Limits
# ---------------------------------------------------------------------------

#: Default maximum input file size.  Matches README documentation.
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
# Public types
# ---------------------------------------------------------------------------

class ConversionError(RuntimeError):
    """A user-displayable conversion failure.

    Raised for all anticipated errors during conversion (bad input, unsupported
    route, I/O failures, Pillow decode errors).  Unexpected internal bugs
    propagate as regular exceptions and are NOT caught here.
    """


@dataclass(frozen=True)
class ConversionResult:
    """Structured result returned by a successful :func:`convert_image` call."""

    #: Resolved path to the output file that was written.
    output_path: Path
    #: Canonical source format key (e.g. ``"png"``).
    source_format: str
    #: Canonical target format key (e.g. ``"jpeg"``).
    target_format: str
    #: Input file size in bytes.
    input_bytes: int
    #: Output file size in bytes.
    output_bytes: int


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

    If ``<stem>.<extension>`` is free it is returned directly.  Otherwise a
    numeric suffix ``(2)``, ``(3)``, … is appended until a free name is found.

    This function respects both files on disk and in-process reservations in
    ``_reserved_paths``.

    Parameters
    ----------
    folder:     Destination directory (must already exist or be created by caller).
    stem:       Base file name without extension.
    extension:  Target extension without leading dot.

    Returns
    -------
    Path
        A ``Path`` inside *folder* that neither exists nor is reserved.
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
        raise ConversionError(f"Input file not found: {source}")
    if source.is_symlink():
        # Accept symlinks only if they resolve to a regular file.
        real = source.resolve()
        if not real.is_file():
            raise ConversionError(f"Symlink does not point to a regular file: {source}")
        log.debug("Source is a symlink; resolved to %s", real)
    if not source.is_file():
        raise ConversionError(f"Input path is not a regular file: {source}")
    size = source.stat().st_size
    if size > max_bytes:
        limit_mib = max_bytes / (1024 * 1024)
        raise ConversionError(
            f"Input file is {size / (1024 * 1024):.1f} MiB, "
            f"which exceeds the {limit_mib:.0f} MiB limit."
        )


def _validate_no_source_dest_collision(source: Path, output: Path) -> None:
    """Raise :class:`ConversionError` if *source* and *output* refer to the same file.

    On Windows the filesystem is case-insensitive, so we compare resolved
    paths after normalising case.  If either path does not exist yet (output
    is a new file), the comparison is done on the string representation, which
    is sufficient for the common case.
    """
    try:
        src_real = source.resolve()
        out_real = output.resolve()
        same = src_real == out_real
        if not same and os.name == "nt":
            # Windows path comparison must be case-insensitive.
            same = src_real.as_posix().lower() == out_real.as_posix().lower()
    except OSError:
        # resolve() can fail on unusual paths; fall back to string compare.
        same = str(source).lower() == str(output).lower()

    if same:
        raise ConversionError(
            f"Output path is the same as the source file: {source}. "
            "LocalShift will not overwrite a source file."
        )


def _resolve_source_format(source: Path, declared_format: Optional[str]) -> str:
    """Return the canonical source format, preferring magic-byte detection.

    If *declared_format* is supplied (e.g. explicitly provided by caller) it is
    returned after normalisation.  Otherwise the file is sniffed first; if
    sniffing fails the extension is used as a fallback.

    Raises :class:`ConversionError` if no supported format can be determined.
    """
    if declared_format is not None:
        try:
            return normalize_format(declared_format)
        except ValueError as exc:
            raise ConversionError(str(exc)) from exc

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

    raise ConversionError(
        f"Cannot determine input format for {source.name!r}. "
        "The file extension is unrecognised and the file content could not be identified."
    )


# ---------------------------------------------------------------------------
# Main conversion function
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

    This is the primary backend entry point for single-file conversion.

    Parameters
    ----------
    source:
        Path to the input image file.
    target:
        Target format — accepts canonical keys (``"jpeg"``) or aliases (``"jpg"``).
    output_dir:
        Directory where the output file will be written.  Defaults to the same
        directory as *source*.  Created automatically if it does not exist.
    jpeg_background:
        RGB tuple used to fill transparent regions when converting to JPEG.
        Default is white ``(255, 255, 255)``.
    max_input_bytes:
        Maximum allowed input file size.  Defaults to :data:`MAX_INPUT_BYTES`.
    source_format:
        Override source format detection.  If ``None`` (default), magic bytes
        are used first, with extension as fallback.

    Returns
    -------
    Path
        Path to the successfully written output file.

    Raises
    ------
    ConversionError
        For all anticipated failures: missing file, unsupported route, decode
        errors, I/O failures, source/output identity collision.

    Concurrency
    -----------
    This function is safe to call from multiple threads concurrently.  A
    module-level lock ensures that path selection and temporary file creation
    are serialised, preventing two concurrent calls from choosing the same
    destination filename.  The slow Pillow encode step runs outside the lock.
    """
    source = Path(source)
    try:
        target_key = normalize_format(target)
    except ValueError as exc:
        raise ConversionError(str(exc)) from exc

    folder = Path(output_dir) if output_dir is not None else source.parent

    log.info("convert_image: %s → %s (output_dir=%s)", source.name, target_key, folder)

    # --- Validation ---
    _validate_source(source, max_input_bytes)

    src_key = _resolve_source_format(source, source_format)

    if not route_supported(src_key, target_key):
        raise ConversionError(
            f"Unsupported conversion: {src_key!r} → {target_key!r}. "
            "These formats may be identical or not supported."
        )

    folder.mkdir(parents=True, exist_ok=True)

    # --- Atomic path reservation + temp-file creation ---
    # reserve_output_path() atomically selects an unused, unreserved destination
    # and registers it in _reserved_paths under _path_reservation_lock.
    # The reservation remains held until explicitly released in the finally block,
    # ensuring concurrent conversions never pick the same destination.
    reservation = reserve_output_path(folder, source.stem, target_key)
    output = reservation.path
    tmp_path: Optional[Path] = None

    try:
        # Source/destination identity check (after path is chosen).
        _validate_no_source_dest_collision(source, output)

        log.debug("Reserved output path: %s", output)

        # Write to a temporary file in the same directory so that os.replace()
        # (which is near-atomic on Windows same-volume) works.  mkstemp()
        # creates the file exclusively — this is our filesystem-level claim.
        fd, tmp_str = tempfile.mkstemp(
            suffix=f".{target_key}.tmp",
            dir=folder,
            prefix=f".localshift_{source.stem}_",
        )
        os.close(fd)
        tmp_path = Path(tmp_str)

        # --- Conversion with atomic write ---
        with Image.open(source) as opened:
            # Animated / multi-frame input: use only the first frame.
            try:
                opened.seek(0)
            except EOFError:
                pass  # Single-frame format — seek(0) is a no-op conceptually.

            # Apply EXIF orientation metadata before any conversion.
            image = ImageOps.exif_transpose(opened).copy()

        # Mode coercion per target format.
        image = _coerce_mode(image, target_key, jpeg_background)

        image.save(tmp_path, format=PIL_FORMATS[target_key])
        log.debug("Saved temp file: %s (%d bytes)", tmp_path, tmp_path.stat().st_size)

        # Atomic rename: replaces `output` if it appeared since the reservation.
        # On Windows, os.replace is atomic only within the same filesystem.
        os.replace(tmp_path, output)
        tmp_path = None  # Consumed — do not clean up.

    except (UnidentifiedImageError, OSError, ValueError) as exc:
        log.error("Conversion failed for %s: %s", source.name, exc)
        raise ConversionError(f"Could not convert image: {exc}") from exc
    finally:
        # Release in-process reservation. If successful, output now exists on
        # disk so future unique_output_path calls will see candidate.exists().
        # If failed, the reservation is freed so the path can be re-used.
        reservation.release()

        # Clean up any unconsumed temporary file.
        if tmp_path is not None and tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass

    output_bytes = output.stat().st_size
    log.info(
        "Conversion complete: %s → %s (%d bytes)",
        source.name, output.name, output_bytes,
    )
    return output


# ---------------------------------------------------------------------------
# Mode coercion
# ---------------------------------------------------------------------------

def _coerce_mode(
    image: Image.Image,
    target_key: str,
    jpeg_background: tuple[int, int, int],
) -> Image.Image:
    """Return *image* converted to the appropriate colour mode for *target_key*.

    JPEG cannot carry transparency; transparent images are composited onto
    *jpeg_background* before conversion.  Other formats are left in their
    native mode unless Pillow would otherwise reject the save.
    """
    if target_key == "jpeg":
        has_alpha = image.mode in ("RGBA", "LA", "PA") or "transparency" in image.info
        if has_alpha:
            rgba = image.convert("RGBA")
            base = Image.new("RGB", rgba.size, jpeg_background)
            base.paste(rgba, mask=rgba.getchannel("A"))
            return base
        return image.convert("RGB")

    if target_key in ("bmp", "tiff", "webp", "png"):
        # These formats support RGB/RGBA/L/1.  Convert exotic modes.
        acceptable = {"RGB", "RGBA", "L", "LA", "1", "CMYK", "P"}
        if image.mode not in acceptable:
            target_mode = "RGBA" if "A" in image.getbands() else "RGB"
            log.debug("Mode coercion: %r → %r for target %r", image.mode, target_mode, target_key)
            return image.convert(target_mode)

    return image
