"""
localshift.adapters.image — Raster image adapter utilizing Pillow.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from PIL import Image, ImageOps, UnidentifiedImageError

from ..exceptions import ConversionCancelledError, ConversionFailedError
from ..models import ConversionContext, ConversionRequest, ConversionResult

log = logging.getLogger(__name__)

#: Supported canonical raster format keys.
IMAGE_FORMATS: frozenset[str] = frozenset({"png", "jpeg", "webp", "bmp", "tiff"})

#: Mapping of canonical format key to Pillow save format string.
PIL_SAVE_FORMATS: dict[str, str] = {
    "png": "PNG",
    "jpeg": "JPEG",
    "webp": "WEBP",
    "bmp": "BMP",
    "tiff": "TIFF",
}


def _coerce_image_mode(
    image: Image.Image,
    target_key: str,
    jpeg_background: tuple[int, int, int],
) -> Image.Image:
    """Return *image* converted to the appropriate colour mode for *target_key*."""
    if target_key == "jpeg":
        has_alpha = image.mode in ("RGBA", "LA", "PA") or "transparency" in image.info
        if has_alpha:
            rgba = image.convert("RGBA")
            base = Image.new("RGB", rgba.size, jpeg_background)
            base.paste(rgba, mask=rgba.getchannel("A"))
            return base
        return image.convert("RGB")

    if target_key in ("bmp", "tiff", "webp", "png"):
        acceptable = {"RGB", "RGBA", "L", "LA", "1", "CMYK", "P"}
        if image.mode not in acceptable:
            target_mode = "RGBA" if "A" in image.getbands() else "RGB"
            log.debug("Mode coercion: %r → %r for target %r", image.mode, target_mode, target_key)
            return image.convert(target_mode)

    return image


class PillowImageAdapter:
    """Conversion adapter for raster image formats supported by Pillow."""

    adapter_id: str = "pillow_raster"
    name: str = "Pillow Raster Image Adapter"

    def __init__(self) -> None:
        self._source_formats = frozenset(IMAGE_FORMATS)
        self._target_formats = frozenset(IMAGE_FORMATS)
        self._routes = frozenset(
            (s, t) for s in IMAGE_FORMATS for t in IMAGE_FORMATS if s != t
        )

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
    ) -> tuple[Any, ...]:
        """Return supported options for raster conversions."""
        from ..models import OptionSpec

        if target_format == "jpeg":
            return (
                OptionSpec(
                    name="jpeg_background",
                    type_name="tuple[int, int, int]",
                    default=(255, 255, 255),
                    description="RGB color tuple (0-255 each) used to replace transparent backgrounds.",
                ),
            )
        return ()

    def convert(
        self,
        request: ConversionRequest,
        context: ConversionContext,
    ) -> ConversionResult:
        """Convert a raster image from request.source to context.temp_output_path."""
        context.check_cancelled()

        target_key = context.target_format
        if target_key not in PIL_SAVE_FORMATS:
            raise ConversionFailedError(f"Unsupported target format for Pillow: {target_key!r}")

        jpeg_bg = request.options.get("jpeg_background", (255, 255, 255))
        source_format = request.source_format or "unknown"

        try:
            input_bytes = request.source.stat().st_size
        except OSError:
            input_bytes = 0

        try:
            with Image.open(request.source) as opened:
                try:
                    opened.seek(0)
                except EOFError:
                    pass

                image = ImageOps.exif_transpose(opened).copy()

            context.check_cancelled()

            image = _coerce_image_mode(image, target_key, jpeg_bg)

            image.save(context.temp_output_path, format=PIL_SAVE_FORMATS[target_key])
            log.debug("Saved temp image file: %s", context.temp_output_path)

        except ConversionCancelledError:
            raise
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            log.error("Pillow conversion failed for %s: %s", request.source.name, exc)
            raise ConversionFailedError(f"Could not convert image: {exc}") from exc
        except Exception as exc:
            log.exception("Unexpected error in Pillow conversion for %s", request.source.name)
            raise ConversionFailedError(f"Could not convert image: {exc}") from exc

        try:
            output_bytes = context.temp_output_path.stat().st_size
        except OSError:
            output_bytes = 0

        return ConversionResult(
            output_path=context.temp_output_path,  # Final destination assigned by core engine
            source_format=source_format,
            target_format=target_key,
            input_bytes=input_bytes,
            output_bytes=output_bytes,
            adapter_id=self.adapter_id,
        )
