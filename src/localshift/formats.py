"""
localshift.formats — Format registry and format identification.

Responsibilities:
- Canonical format names (internal identifiers, not display labels).
- Extension aliases and normalisation.
- PIL/Pillow format name mapping.
- Route capability queries.
- Magic-byte content sniffing (via Pillow) for accurate format detection.

This module has NO dependency on PySide6 or the GUI layer.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Format definitions
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FormatInfo:
    """Immutable descriptor for a supported image format."""

    #: Internal canonical identifier (lowercase, no dot).
    key: str
    #: Human-readable display label.
    label: str
    #: Pillow format string used in ``Image.save(format=...)``.
    pil_format: str
    #: File extensions (without dot) that map to this format.
    extensions: tuple[str, ...] = field(default_factory=tuple)


# Canonical format registry — single source of truth.
_REGISTRY: dict[str, FormatInfo] = {
    info.key: info
    for info in [
        FormatInfo("png",  "PNG image",    "PNG",  ("png",)),
        FormatInfo("jpeg", "JPEG image",   "JPEG", ("jpeg", "jpg")),
        FormatInfo("webp", "WebP image",   "WEBP", ("webp",)),
        FormatInfo("bmp",  "BMP image",    "BMP",  ("bmp",)),
        FormatInfo("tiff", "TIFF image",   "TIFF", ("tiff", "tif")),
        FormatInfo("gif",  "GIF image",    "GIF",  ("gif",)),
        FormatInfo("ico",  "ICO icon",     "ICO",  ("ico",)),
        FormatInfo("pdf",  "PDF document", "",     ("pdf",)),
        FormatInfo("txt",  "Plain text",   "",     ("txt",)),
        FormatInfo("docx", "Word document", "",    ("docx",)),
    ]
}

# Extension → canonical key lookup (includes aliases).
_EXT_ALIAS: dict[str, str] = {
    ext: info.key
    for info in _REGISTRY.values()
    for ext in info.extensions
}

# ---------------------------------------------------------------------------
# Public API: Constants kept for backwards compatibility with existing callers
# (gui.py, cli.py, tests).
# ---------------------------------------------------------------------------

#: Mapping of canonical key → display label.
FORMAT_LABELS: dict[str, str] = {k: v.label for k, v in _REGISTRY.items()}

#: Mapping of canonical key → Pillow format string (image formats only).
PIL_FORMATS: dict[str, str] = {
    k: v.pil_format for k, v in _REGISTRY.items() if v.pil_format
}

#: Frozenset of all canonical format keys.
SUPPORTED: frozenset[str] = frozenset(_REGISTRY)

#: Extension alias table (backwards compatibility).
ALIASES: dict[str, str] = {
    ext: key
    for key, info in _REGISTRY.items()
    for ext in info.extensions
    if ext != key
}


# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------

def normalize_format(value: str) -> str:
    """Return the canonical format key for *value*.

    Accepts canonical keys, extension aliases, and dotted extensions.
    Raises ``UnsupportedFormatError`` (a ``ValueError`` subclass) if *value*
    is not a recognised format string.
    """
    from .exceptions import UnsupportedFormatError

    norm = value.lower().strip().lstrip(".")
    result = _EXT_ALIAS.get(norm)
    if result is None:
        # Try direct key lookup (e.g. "jpeg" is already canonical).
        result = norm if norm in _REGISTRY else None
    if result is None:
        raise UnsupportedFormatError(f"Unknown format specifier: {value!r}")
    return result


def input_format(path: Path) -> Optional[str]:
    """Return the canonical format key inferred from *path*'s extension.

    Returns ``None`` if the extension is unrecognised.
    This does **not** read the file; use :func:`sniff_format` for that.
    """
    ext = path.suffix.lower().lstrip(".")
    return _EXT_ALIAS.get(ext)


def sniff_format(path: Path) -> Optional[str]:
    """Return the canonical format key determined by reading *path*'s magic bytes.

    Uses magic byte inspection for documents (e.g. %PDF-) and Pillow's format
    identification for images. Returns ``None`` if the format cannot be identified
    or is not in the LocalShift registry.

    This is more reliable than extension-only detection and guards against
    misnamed files.
    """
    # 1. Quick magic byte check for document formats (PDF, DOCX)
    try:
        with open(path, "rb") as f:
            header = f.read(5)
            if header.startswith(b"%PDF-"):
                return "pdf"
            if header.startswith(b"PK\x03\x04"):
                import zipfile
                if zipfile.is_zipfile(path):
                    with zipfile.ZipFile(path, "r") as zf:
                        if "word/document.xml" in zf.namelist():
                            return "docx"
    except (OSError, PermissionError):
        pass

    # 2. Pillow image format identification
    from PIL import Image, UnidentifiedImageError  # local import keeps module lighter

    try:
        with Image.open(path) as im:
            pil_fmt = (im.format or "").upper()
    except (UnidentifiedImageError, OSError) as exc:
        log.debug("sniff_format: could not open %s — %s", path, exc)
        return None

    # Reverse-map PIL format string → canonical key.
    for key, info in _REGISTRY.items():
        if info.pil_format and info.pil_format == pil_fmt:
            return key

    log.debug("sniff_format: PIL format %r for %s not in registry", pil_fmt, path)
    return None


# ---------------------------------------------------------------------------
# Capability queries
# ---------------------------------------------------------------------------

def output_formats_for(path: Path) -> list[str]:
    """Return sorted list of canonical target format keys available for *path*.

    Uses extension-based detection (does not read the file).  Returns an empty
    list if the source format is unrecognised or unsupported.
    """
    source = input_format(path)
    if source is None:
        return []
    from .registry import default_registry

    targets = default_registry.supported_target_formats(source)
    return sorted(targets)


def route_supported(source: str, target: str) -> bool:
    """Return ``True`` if the ``source → target`` conversion route exists.

    Both arguments are normalised before comparison, so aliases (e.g. ``"jpg"``)
    are accepted.  Returns ``False`` rather than raising for unknown formats.
    """
    try:
        src = normalize_format(source)
        tgt = normalize_format(target)
    except (ValueError, Exception):
        return False
    from .registry import default_registry

    return default_registry.can_convert(src, tgt)


def get_format_info(key: str) -> Optional[FormatInfo]:
    """Return the :class:`FormatInfo` for *key*, or ``None`` if unknown."""
    try:
        return _REGISTRY.get(normalize_format(key))
    except (ValueError, Exception):
        return None
