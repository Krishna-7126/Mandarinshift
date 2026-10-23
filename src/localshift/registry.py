"""
localshift.registry — Adapter protocol and centralized capability registry.
"""
from __future__ import annotations

import logging
import threading
from typing import Optional, Protocol, runtime_checkable

from .exceptions import AdapterRegistrationError
from .models import ConversionContext, ConversionRequest, ConversionResult

log = logging.getLogger(__name__)


@runtime_checkable
class ConversionAdapter(Protocol):
    """Protocol defining the interface for LocalShift conversion adapters."""

    adapter_id: str
    name: str

    @property
    def supported_source_formats(self) -> frozenset[str]:
        """Set of canonical source format keys accepted by this adapter."""
        ...

    @property
    def supported_target_formats(self) -> frozenset[str]:
        """Set of canonical target format keys producible by this adapter."""
        ...

    @property
    def supported_routes(self) -> frozenset[tuple[str, str]]:
        """Set of explicit directional (source, target) format pairs supported."""
        ...

    def can_convert(self, source_format: str, target_format: str) -> bool:
        """Return True if this adapter supports converting source_format to target_format."""
        ...

    def convert(
        self,
        request: ConversionRequest,
        context: ConversionContext,
    ) -> ConversionResult:
        """Execute the conversion, writing output directly to context.temp_output_path.

        Parameters
        ----------
        request:
            Immutable request specification with source path and options.
        context:
            Execution context providing the secure temp file destination and
            cancellation checks.

        Returns
        -------
        ConversionResult
            Structured result containing metadata and output sizes.
        """
        ...


class AdapterRegistry:
    """Thread-safe centralized capability registry for conversion adapters.

    Maintains:
    - Registered adapters indexed by ``adapter_id``
    - Directional route table ``(source, target) -> ConversionAdapter``

    Conflict policy:
    - Duplicate ``adapter_id`` raises :class:`AdapterRegistrationError` unless
      ``allow_override=True``.
    - Ambiguous or conflicting routes (where route ``(src, tgt)`` is already
      claimed by another adapter) raise :class:`AdapterRegistrationError` unless
      ``allow_override=True``.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._adapters: dict[str, ConversionAdapter] = {}
        # Route table mapping (canonical_source, canonical_target) -> adapter
        self._routes: dict[tuple[str, str], ConversionAdapter] = {}

    def register(self, adapter: ConversionAdapter, *, allow_override: bool = False) -> None:
        """Register an adapter and its declared conversion routes.

        Parameters
        ----------
        adapter:
            An instance implementing :class:`ConversionAdapter`.
        allow_override:
            If False (default), conflicting routes or duplicate adapter IDs raise
            :class:`AdapterRegistrationError`. If True, existing registrations are
            superseded.
        """
        if not getattr(adapter, "adapter_id", None) or not isinstance(adapter.adapter_id, str):
            raise AdapterRegistrationError(
                f"Invalid adapter: 'adapter_id' must be a non-empty string, got {adapter!r}"
            )

        with self._lock:
            existing = self._adapters.get(adapter.adapter_id)
            if existing is not None and not allow_override and existing is not adapter:
                raise AdapterRegistrationError(
                    f"Adapter with ID {adapter.adapter_id!r} is already registered "
                    f"({existing.name}). Set allow_override=True to replace."
                )

            # Check for route collisions with OTHER adapters
            routes = adapter.supported_routes
            for route in routes:
                src, tgt = route
                current_owner = self._routes.get((src, tgt))
                if (
                    current_owner is not None
                    and current_owner.adapter_id != adapter.adapter_id
                    and not allow_override
                ):
                    raise AdapterRegistrationError(
                        f"Route conflict for {src!r} → {tgt!r}: already registered "
                        f"by adapter {current_owner.adapter_id!r} ({current_owner.name})."
                    )

            # Apply registration
            self._adapters[adapter.adapter_id] = adapter
            for route in routes:
                self._routes[route] = adapter

            log.debug(
                "Registered adapter %r (%s) with %d routes",
                adapter.adapter_id, adapter.name, len(routes),
            )

    def unregister(self, adapter_id: str) -> Optional[ConversionAdapter]:
        """Remove an adapter and its exclusive routes from the registry."""
        with self._lock:
            adapter = self._adapters.pop(adapter_id, None)
            if adapter is None:
                return None

            # Remove associated routes
            routes_to_remove = [
                route for route, a in self._routes.items()
                if a.adapter_id == adapter_id
            ]
            for r in routes_to_remove:
                del self._routes[r]

            log.debug("Unregistered adapter %r", adapter_id)
            return adapter

    def get_adapter(self, source_format: str, target_format: str) -> Optional[ConversionAdapter]:
        """Return the adapter registered for ``(source_format, target_format)``, or None."""
        with self._lock:
            return self._routes.get((source_format, target_format))

    def can_convert(self, source_format: str, target_format: str) -> bool:
        """Return True if an adapter is available for ``(source_format, target_format)``."""
        with self._lock:
            return (source_format, target_format) in self._routes

    def supported_routes(self) -> frozenset[tuple[str, str]]:
        """Return all registered directional conversion routes."""
        with self._lock:
            return frozenset(self._routes.keys())

    def supported_source_formats(self) -> frozenset[str]:
        """Return all formats that can act as conversion inputs."""
        with self._lock:
            return frozenset(src for src, _ in self._routes.keys())

    def supported_target_formats(self, source_format: Optional[str] = None) -> frozenset[str]:
        """Return all target formats, optionally filtered by a specific source format."""
        with self._lock:
            if source_format is None:
                return frozenset(tgt for _, tgt in self._routes.keys())
            return frozenset(tgt for src, tgt in self._routes.keys() if src == source_format)

    def get_supported_options(self, source_format: str, target_format: str) -> tuple[Any, ...]:
        """Return supported OptionSpec instances for the given route, or empty tuple."""
        with self._lock:
            adapter = self._routes.get((source_format, target_format))
            if adapter is None or not hasattr(adapter, "get_supported_options"):
                return ()
            return tuple(adapter.get_supported_options(source_format, target_format))

    def get_adapter_by_id(self, adapter_id: str) -> Optional[ConversionAdapter]:
        """Return the adapter with *adapter_id*, or None if not registered."""
        with self._lock:
            return self._adapters.get(adapter_id)

    def list_adapters(self) -> list[ConversionAdapter]:
        """Return a snapshot list of all registered adapters."""
        with self._lock:
            return list(self._adapters.values())

    def snapshot(self) -> AdapterRegistry:
        """Create an isolated, shallow-copied snapshot of the current registry."""
        with self._lock:
            snap = AdapterRegistry()
            snap._adapters = dict(self._adapters)
            snap._routes = dict(self._routes)
            return snap


#: Global default registry instance used across LocalShift.
default_registry: AdapterRegistry = AdapterRegistry()

# Pre-register built-in adapters at initialization
from .adapters.image import PillowImageAdapter

default_registry.register(PillowImageAdapter())
