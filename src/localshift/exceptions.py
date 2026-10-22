"""
localshift.exceptions — Structured error taxonomy for LocalShift.

All conversion-related exceptions inherit from :class:`ConversionError`,
preserving 100% backward compatibility with existing callers while allowing
granular error inspection for CLI, GUI, and job management layers.
"""
from __future__ import annotations


class ConversionError(RuntimeError):
    """Base class for all anticipated, user-displayable conversion errors.

    Raised for all anticipated conversion failures (bad input, unsupported
    route, decode/encode errors, destination conflicts).
    """


class UnsupportedFormatError(ConversionError, ValueError):
    """Raised when a format key, alias, or extension is unrecognised."""


class UnsupportedConversionError(ConversionError):
    """Raised when no registered adapter supports the requested conversion route."""


class InvalidInputError(ConversionError):
    """Raised when an input file is missing, not a regular file, or unreadable."""


class InputTooLargeError(InvalidInputError):
    """Raised when an input file exceeds the configured size limit."""


class DestinationConflictError(ConversionError):
    """Raised when source and destination point to the same physical file."""


class AdapterUnavailableError(ConversionError):
    """Raised when a required adapter or its system runtime is not available."""


class ConversionFailedError(ConversionError):
    """Raised when an adapter encounters an error during execution."""


class ConversionCancelledError(ConversionError):
    """Raised when a conversion is cancelled before or during execution."""


class AdapterRegistrationError(RuntimeError):
    """Raised when adapter registration fails (duplicate id, conflicting route)."""
