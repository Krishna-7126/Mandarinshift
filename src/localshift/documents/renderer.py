"""
localshift.documents.renderer — Bounded, resource-aware PDF page rasterization.

Provides safe page rendering using pypdfium2 with strict pixel-count boundaries,
memory protections against malicious dimensions, rotation preservation, and
explicit bitmap resource reclamation.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from ..exceptions import InvalidInputError

log = logging.getLogger(__name__)


class PdfPageRenderer:
    """Bounded PDF page rasterizer with memory limit protections."""

    DEFAULT_DPI: int = 200
    MIN_DPI: int = 72
    MAX_DPI: int = 400

    # Maximum raster pixel count per page (e.g., 4000 x 4000 = 16 MP ~ 48 MB raw RGB buffer)
    MAX_IMAGE_PIXELS: int = 16_000_000

    # Maximum PDF page dimension in points per ISO 32000 (200 inches = 14,400 points)
    MAX_PAGE_POINTS: float = 14_400.0

    @classmethod
    def render_page(
        cls,
        page: Any,
        *,
        dpi: int = DEFAULT_DPI,
        max_pixels: int = MAX_IMAGE_PIXELS,
    ) -> Any:
        """Render a single pypdfium2 PDF page to an RGB numpy array.

        Enforces bounded scaling, rotation compliance, and immediate cleanup
        of internal PDFium native bitmap buffers.
        """
        try:
            width_pts, height_pts = page.get_size()
        except Exception as exc:
            raise InvalidInputError(f"Could not read page dimensions: {exc}") from exc

        if width_pts <= 0 or height_pts <= 0:
            raise InvalidInputError(f"Invalid page dimensions: {width_pts}x{height_pts}")

        if width_pts > cls.MAX_PAGE_POINTS or height_pts > cls.MAX_PAGE_POINTS:
            raise InvalidInputError(
                f"Page dimensions ({width_pts:.1f}x{height_pts:.1f} pts) exceed maximum limit of {cls.MAX_PAGE_POINTS} pts."
            )

        # Clamp requested DPI within safe operational range
        effective_dpi = max(cls.MIN_DPI, min(dpi, cls.MAX_DPI))
        scale = effective_dpi / 72.0

        est_pixels = (width_pts * scale) * (height_pts * scale)
        if est_pixels > max_pixels:
            # Scale down proportionally to respect the pixel ceiling
            scale = (max_pixels / (width_pts * height_pts)) ** 0.5
            log.warning(
                "Page dimensions (%0.1fx%0.1f) would produce %d pixels at %d DPI; clamping scale to %0.2f (%d max pixels)",
                width_pts, height_pts, int(est_pixels), effective_dpi, scale, max_pixels,
            )

        bmp = None
        try:
            bmp = page.render(scale=scale)
            # Explicit copy ensures NumPy owns its memory before bmp is closed
            img_arr = bmp.to_numpy().copy()
            return img_arr
        except Exception as exc:
            log.exception("Failed to render PDF page at scale %.2f: %s", scale, exc)
            raise InvalidInputError(f"Failed to render PDF page: {exc}") from exc
        finally:
            if bmp is not None:
                try:
                    bmp.close()
                except Exception:
                    pass
