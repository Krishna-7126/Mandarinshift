"""
localshift.documents.image_to_pdf — Offline Image to PDF conversion engine.

Provides robust, memory-bounded conversion of raster images (PNG, JPEG, WebP,
BMP, TIFF) into single-page or multi-page PDF documents.

Key features:
- Single image → single-page PDF.
- Multiple images → one ordered multipage PDF.
- Configurable page size ('a4', 'letter', 'original'/'fit_to_image').
- Scaling modes: 'contain' (preserve aspect ratio, letterbox) and 'cover' (fill, center crop).
- Orientation: 'auto' (inferred from image aspect ratio), 'portrait', or 'landscape'.
- Configurable margins (in points) and background color for padding and transparency.
- EXIF orientation transposition and alpha channel compositing.
- DPI scaling (72–400) and JPEG compression quality control (1–100).
- Cooperative cancellation and resource-bounded processing.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

from PIL import Image, ImageOps, UnidentifiedImageError

from ..exceptions import (
    ConversionCancelledError,
    ConversionFailedError,
    InputTooLargeError,
    InvalidInputError,
)
from ..models import (
    ConversionContext,
    ConversionRequest,
    ConversionResult,
    OptionSpec,
)

log = logging.getLogger(__name__)

#: Supported canonical raster format keys.
SUPPORTED_IMAGE_FORMATS: frozenset[str] = frozenset(
    {"png", "jpeg", "webp", "bmp", "tiff", "gif", "ico"}
)

#: Standard page dimensions in PostScript points (1/72 inch).
PAGE_SIZES: dict[str, tuple[float, float]] = {
    "a4": (595.28, 841.89),       # 210 x 297 mm
    "letter": (612.0, 792.0),     # 8.5 x 11.0 in
}

MIN_DPI: int = 72
MAX_DPI: int = 400
DEFAULT_DPI: int = 150

MIN_QUALITY: int = 1
MAX_QUALITY: int = 100
DEFAULT_QUALITY: int = 85

MAX_IMAGE_PIXELS: int = 64_000_000


class ImageToPdfConverter:
    """Core image-to-PDF transformation and assembly engine."""

    @classmethod
    def validate_options(cls, options: dict[str, Any]) -> dict[str, Any]:
        """Validate and normalize options dictionary for Image → PDF conversion."""
        validated: dict[str, Any] = dict(options)

        # Page size
        page_size = str(options.get("page_size", "a4")).lower().strip()
        allowed_page_sizes = {"a4", "letter", "original", "fit_to_image", "image"}
        if page_size not in allowed_page_sizes:
            raise InvalidInputError(
                f"Invalid page_size {page_size!r}. Allowed: {sorted(allowed_page_sizes)}"
            )
        validated["page_size"] = page_size

        # Fit mode
        fit = str(options.get("fit", "contain")).lower().strip()
        allowed_fits = {"contain", "cover"}
        if fit not in allowed_fits:
            raise InvalidInputError(
                f"Invalid fit mode {fit!r}. Allowed: {sorted(allowed_fits)}"
            )
        validated["fit"] = fit

        # Orientation
        orientation = str(options.get("orientation", "auto")).lower().strip()
        allowed_orientations = {"auto", "portrait", "landscape"}
        if orientation not in allowed_orientations:
            raise InvalidInputError(
                f"Invalid orientation {orientation!r}. Allowed: {sorted(allowed_orientations)}"
            )
        validated["orientation"] = orientation

        # Margin
        margin = options.get("margin", 0.0)
        try:
            m_val = float(margin)
        except (ValueError, TypeError) as exc:
            raise InvalidInputError(f"Margin must be a numeric value, got {margin!r}") from exc
        if m_val < 0:
            raise InvalidInputError(f"Margin must be non-negative, got {m_val}")
        validated["margin"] = m_val

        # Background color
        bg = options.get("background_color") or options.get("background") or (255, 255, 255)
        if not isinstance(bg, (tuple, list)) or len(bg) != 3 or not all(
            isinstance(c, int) and 0 <= c <= 255 for c in bg
        ):
            raise InvalidInputError(
                f"Background color must be an RGB 3-tuple of integers (0–255), got {bg!r}"
            )
        validated["background_color"] = tuple(bg)

        # DPI
        dpi = options.get("dpi", DEFAULT_DPI)
        try:
            dpi_val = int(dpi)
        except (ValueError, TypeError) as exc:
            raise InvalidInputError(f"DPI must be an integer, got {dpi!r}") from exc
        if dpi_val < MIN_DPI or dpi_val > MAX_DPI:
            raise InvalidInputError(
                f"DPI must be between {MIN_DPI} and {MAX_DPI}, got {dpi_val}"
            )
        validated["dpi"] = dpi_val

        # Quality
        quality = options.get("quality", DEFAULT_QUALITY)
        try:
            q_val = int(quality)
        except (ValueError, TypeError) as exc:
            raise InvalidInputError(f"Quality must be an integer, got {quality!r}") from exc
        if q_val < MIN_QUALITY or q_val > MAX_QUALITY:
            raise InvalidInputError(
                f"Quality must be between {MIN_QUALITY} and {MAX_QUALITY}, got {q_val}"
            )
        validated["quality"] = q_val

        # Additional sources
        extra = options.get("additional_sources") or options.get("images") or options.get("sources")
        if extra is not None:
            if not isinstance(extra, (list, tuple)):
                raise InvalidInputError(
                    f"Additional sources must be a sequence of paths, got {type(extra).__name__!r}"
                )
            validated["additional_sources"] = tuple(Path(p) for p in extra)
        else:
            validated["additional_sources"] = ()

        return validated

    @classmethod
    def prepare_page(
        cls,
        image_path: Path,
        *,
        page_size: str = "a4",
        fit: str = "contain",
        orientation: str = "auto",
        margin: float = 0.0,
        background_color: tuple[int, int, int] = (255, 255, 255),
        dpi: int = DEFAULT_DPI,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> Image.Image:
        """Load, normalize, and render a single raster image onto a PDF page canvas."""
        if cancel_check and cancel_check():
            raise ConversionCancelledError("Conversion was cancelled.")

        if not image_path.is_file():
            raise InvalidInputError(f"Source image does not exist or is not a file: {image_path}")

        try:
            file_size = image_path.stat().st_size
        except OSError as exc:
            raise InvalidInputError(f"Cannot read source image: {exc}") from exc

        if file_size == 0:
            raise InvalidInputError(f"Source image is empty (0 bytes): {image_path.name}")

        try:
            with Image.open(image_path) as opened:
                try:
                    opened.seek(0)
                except EOFError:
                    pass

                # Check pixel limits before allocating memory
                w, h = opened.size
                if w <= 0 or h <= 0:
                    raise InvalidInputError(f"Invalid image dimensions: {w}x{h}")
                if w * h > MAX_IMAGE_PIXELS:
                    raise InputTooLargeError(
                        f"Image pixel count ({w * h:,}) exceeds maximum ceiling ({MAX_IMAGE_PIXELS:,})."
                    )

                # Transpose according to EXIF orientation
                img = ImageOps.exif_transpose(opened)
                img.load()
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise InvalidInputError(f"Cannot decode image {image_path.name}: {exc}") from exc

        if cancel_check and cancel_check():
            raise ConversionCancelledError("Conversion was cancelled.")

        # Composite transparency or convert non-RGB modes
        if img.mode in ("RGBA", "LA", "PA") or "transparency" in img.info:
            rgba = img.convert("RGBA")
            bg_img = Image.new("RGB", rgba.size, background_color)
            bg_img.paste(rgba, mask=rgba.getchannel("A"))
            img = bg_img
        elif img.mode == "CMYK":
            img = img.convert("RGB")
        elif img.mode != "RGB":
            img = img.convert("RGB")

        # Determine page dimensions in points
        img_w_px, img_h_px = img.size
        is_original = page_size in ("original", "fit_to_image", "image")

        if is_original:
            page_w_pt = img_w_px * 72.0 / dpi + 2.0 * margin
            page_h_pt = img_h_px * 72.0 / dpi + 2.0 * margin
        else:
            base_w, base_h = PAGE_SIZES[page_size]
            if orientation == "portrait":
                page_w_pt, page_h_pt = min(base_w, base_h), max(base_w, base_h)
            elif orientation == "landscape":
                page_w_pt, page_h_pt = max(base_w, base_h), min(base_w, base_h)
            else:  # auto
                if img_w_px > img_h_px:
                    page_w_pt, page_h_pt = max(base_w, base_h), min(base_w, base_h)
                else:
                    page_w_pt, page_h_pt = min(base_w, base_h), max(base_w, base_h)

        # Check margin bounds
        print_w_pt = page_w_pt - 2.0 * margin
        print_h_pt = page_h_pt - 2.0 * margin
        if print_w_pt <= 0 or print_h_pt <= 0:
            raise InvalidInputError(
                f"Margin {margin}pt exceeds page dimensions ({page_w_pt:.1f}x{page_h_pt:.1f}pt)."
            )

        # Pixel canvas dimensions
        canvas_w_px = max(1, int(round(page_w_pt * dpi / 72.0)))
        canvas_h_px = max(1, int(round(page_h_pt * dpi / 72.0)))
        print_w_px = max(1, int(round(print_w_pt * dpi / 72.0)))
        print_h_px = max(1, int(round(print_h_pt * dpi / 72.0)))
        margin_x_px = int(round(margin * dpi / 72.0))
        margin_y_px = int(round(margin * dpi / 72.0))

        if is_original and margin == 0.0:
            # Direct natural image
            return img

        # Create page canvas
        canvas = Image.new("RGB", (canvas_w_px, canvas_h_px), background_color)

        if is_original:
            # Original dimensions with margins
            canvas.paste(img, (margin_x_px, margin_y_px))
            return canvas

        # Standard page sizing with contain/cover
        if fit == "cover":
            scale = max(print_w_px / img_w_px, print_h_px / img_h_px)
            scaled_w = max(1, int(round(img_w_px * scale)))
            scaled_h = max(1, int(round(img_h_px * scale)))
            scaled = img.resize((scaled_w, scaled_h), Image.Resampling.LANCZOS)

            crop_x = (scaled_w - print_w_px) // 2
            crop_y = (scaled_h - print_h_px) // 2
            cropped = scaled.crop((crop_x, crop_y, crop_x + print_w_px, crop_y + print_h_px))
            canvas.paste(cropped, (margin_x_px, margin_y_px))
        else:  # contain
            scale = min(print_w_px / img_w_px, print_h_px / img_h_px)
            scaled_w = max(1, int(round(img_w_px * scale)))
            scaled_h = max(1, int(round(img_h_px * scale)))
            scaled = img.resize((scaled_w, scaled_h), Image.Resampling.LANCZOS)

            paste_x = margin_x_px + (print_w_px - scaled_w) // 2
            paste_y = margin_y_px + (print_h_px - scaled_h) // 2
            canvas.paste(scaled, (paste_x, paste_y))

        return canvas

    @classmethod
    def convert_images_to_pdf(
        cls,
        sources: Sequence[Path],
        output_path: Path,
        *,
        options: Optional[dict[str, Any]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> int:
        """Convert one or more raster images into a single PDF document.

        Parameters
        ----------
        sources:
            Ordered sequence of source image file paths.
        output_path:
            Target destination path for the generated PDF.
        options:
            Validated configuration options.
        cancel_check:
            Optional cooperative cancellation callback.

        Returns
        -------
        int
            Number of bytes written to the output PDF.
        """
        if not sources:
            raise InvalidInputError("No source images provided for PDF conversion.")

        opts = cls.validate_options(options or {})
        page_size = opts["page_size"]
        fit = opts["fit"]
        orientation = opts["orientation"]
        margin = opts["margin"]
        bg = opts["background_color"]
        dpi = opts["dpi"]
        quality = opts["quality"]

        prepared_pages: list[Image.Image] = []
        try:
            for src in sources:
                if cancel_check and cancel_check():
                    raise ConversionCancelledError("Conversion was cancelled.")
                page_img = cls.prepare_page(
                    src,
                    page_size=page_size,
                    fit=fit,
                    orientation=orientation,
                    margin=margin,
                    background_color=bg,
                    dpi=dpi,
                    cancel_check=cancel_check,
                )
                prepared_pages.append(page_img)

            if cancel_check and cancel_check():
                raise ConversionCancelledError("Conversion was cancelled.")

            output_path.parent.mkdir(parents=True, exist_ok=True)

            if len(prepared_pages) == 1:
                prepared_pages[0].save(
                    output_path,
                    format="PDF",
                    resolution=float(dpi),
                    quality=quality,
                )
            else:
                prepared_pages[0].save(
                    output_path,
                    format="PDF",
                    save_all=True,
                    append_images=prepared_pages[1:],
                    resolution=float(dpi),
                    quality=quality,
                )

        finally:
            for p in prepared_pages:
                try:
                    p.close()
                except Exception:
                    pass

        try:
            return output_path.stat().st_size
        except OSError:
            return 0


class ImageToPdfAdapter:
    """Conversion adapter for raster image to PDF document routes."""

    adapter_id: str = "image_to_pdf"
    name: str = "Image to PDF Document Adapter"

    def __init__(self) -> None:
        self._source_formats = frozenset(SUPPORTED_IMAGE_FORMATS)
        self._target_formats = frozenset({"pdf"})
        self._routes = frozenset((s, "pdf") for s in SUPPORTED_IMAGE_FORMATS)

    @property
    def supported_source_formats(self) -> frozenset[str]:
        return self._source_formats

    @property
    def supported_target_formats(self) -> frozenset[str]:
        return self._target_formats

    @property
    def supported_routes(self) -> frozenset[tuple[str, str]]:
        return self._routes

    def can_convert(self, source_format: str, target_format: str) -> bool:
        return (source_format, target_format) in self._routes

    def get_supported_options(
        self,
        source_format: str,
        target_format: str,
    ) -> tuple[OptionSpec, ...]:
        """Return option specifications supported for Image → PDF conversions."""
        if target_format != "pdf" or source_format not in self._source_formats:
            return ()

        return (
            OptionSpec(
                name="page_size",
                type_name="str",
                default="a4",
                description="Target PDF page size ('a4', 'letter', or 'original' to match image size).",
                choices=("a4", "letter", "original", "fit_to_image"),
            ),
            OptionSpec(
                name="fit",
                type_name="str",
                default="contain",
                description="Image fitting mode: 'contain' (preserve aspect ratio) or 'cover' (fill page, center crop).",
                choices=("contain", "cover"),
            ),
            OptionSpec(
                name="orientation",
                type_name="str",
                default="auto",
                description="Page orientation: 'auto' (matches image aspect ratio), 'portrait', or 'landscape'.",
                choices=("auto", "portrait", "landscape"),
            ),
            OptionSpec(
                name="margin",
                type_name="float",
                default=0.0,
                description="Page margin in points (default 0). Must not exceed page bounds.",
            ),
            OptionSpec(
                name="background_color",
                type_name="tuple[int, int, int]",
                default=(255, 255, 255),
                description="RGB color tuple (0–255 each) used for page margins and alpha compositing.",
            ),
            OptionSpec(
                name="dpi",
                type_name="int",
                default=DEFAULT_DPI,
                description=f"Output raster resolution in DPI ({MIN_DPI}–{MAX_DPI}, default {DEFAULT_DPI}).",
            ),
            OptionSpec(
                name="quality",
                type_name="int",
                default=DEFAULT_QUALITY,
                description=f"JPEG compression quality level ({MIN_QUALITY}–{MAX_QUALITY}, default {DEFAULT_QUALITY}).",
            ),
            OptionSpec(
                name="additional_sources",
                type_name="tuple[Path, ...]",
                default=(),
                description="Additional image files to assemble into a single ordered multipage PDF.",
            ),
            OptionSpec(
                name="output_name",
                type_name="str",
                default=None,
                description="Base filename without extension for the output PDF.",
            ),
        )

    def convert(
        self,
        request: ConversionRequest,
        context: ConversionContext,
    ) -> ConversionResult:
        """Convert one or more images into a PDF document."""
        context.check_cancelled()

        extra_sources = (
            request.options.get("additional_sources")
            or request.options.get("images")
            or request.options.get("sources")
            or ()
        )
        sources = [request.source] + [Path(p) for p in extra_sources]

        source_format = request.source_format or "unknown"
        input_bytes = sum(s.stat().st_size for s in sources if s.is_file())

        try:
            output_bytes = ImageToPdfConverter.convert_images_to_pdf(
                sources=sources,
                output_path=context.temp_output_path,
                options=request.options,
                cancel_check=context.is_cancelled,
            )
        except (ConversionCancelledError, InvalidInputError, InputTooLargeError):
            raise
        except Exception as exc:
            log.exception("Image to PDF conversion failed for %s", request.source.name)
            raise ConversionFailedError(f"Image to PDF conversion failed: {exc}") from exc

        return ConversionResult(
            output_path=context.temp_output_path,
            source_format=source_format,
            target_format="pdf",
            input_bytes=input_bytes,
            output_bytes=output_bytes,
            adapter_id=self.adapter_id,
        )
