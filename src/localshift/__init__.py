"""
LocalShift — offline-first Windows file converter.

Public API
----------
Callers (CLI, GUI, tests, future integrations) should import from this package
rather than from internal submodules where possible.

    from localshift import convert_image, ConversionError, ConversionResult
    from localshift.formats import SUPPORTED, route_supported, output_formats_for

Backend modules (``converter``, ``formats``, ``cli``) have NO dependency on
PySide6.  Importing ``localshift`` or any backend module is safe without a
display server or GUI toolkit installed.
"""
from __future__ import annotations

__version__ = "0.1.0"
__all__ = [
    "convert_image",
    "ConversionError",
    "ConversionResult",
    "__version__",
]

# Re-export primary backend interface.
from .converter import ConversionError, ConversionResult, convert_image
