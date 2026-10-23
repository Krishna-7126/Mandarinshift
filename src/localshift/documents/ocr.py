"""
localshift.documents.ocr — Offline OCR engine foundation and reading-order reconstruction.

Integrates RapidOCR with ONNX Runtime CPU for fully local, privacy-first,
offline text recognition from scanned PDF pages and raster images.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Optional, Sequence

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class OcrTextBlock:
    """A single recognized text block with geometric coordinates and confidence."""
    box: tuple[tuple[float, float], ...]  # 4-point polygon: ((x0, y0), (x1, y1), (x2, y2), (x3, y3))
    text: str
    confidence: float
    page_number: int
    detection_order: int
    x_min: float
    y_min: float
    x_max: float
    y_max: float

    @property
    def height(self) -> float:
        return max(0.0, self.y_max - self.y_min)

    @property
    def width(self) -> float:
        return max(0.0, self.x_max - self.x_min)

    @classmethod
    def from_raw_detection(
        cls,
        box_points: list[list[float]],
        text: str,
        score: Any,
        *,
        page_number: int = 1,
        detection_order: int = 0,
    ) -> OcrTextBlock:
        """Construct an OcrTextBlock from raw RapidOCR output."""
        pts = tuple((float(p[0]), float(p[1])) for p in box_points)
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        x_min = min(xs) if xs else 0.0
        x_max = max(xs) if xs else 0.0
        y_min = min(ys) if ys else 0.0
        y_max = max(ys) if ys else 0.0

        try:
            conf = float(score)
        except (ValueError, TypeError):
            conf = 0.0

        return cls(
            box=pts,
            text=str(text).strip(),
            confidence=conf,
            page_number=page_number,
            detection_order=detection_order,
            x_min=x_min,
            y_min=y_min,
            x_max=x_max,
            y_max=y_max,
        )


@dataclass(frozen=True)
class OcrPageResult:
    """Structured OCR results for a single page."""
    page_number: int
    text: str
    blocks: tuple[OcrTextBlock, ...]
    mean_confidence: float
    duration_ms: float
    warnings: tuple[str, ...] = ()


def reconstruct_reading_order(blocks: Sequence[OcrTextBlock]) -> str:
    """Group detector-provided text blocks into reading lines and ordered paragraphs.

    Heuristic strategy:
    1. Sort blocks by top coordinate (y_min) and left coordinate (x_min).
    2. Group adjacent blocks into common horizontal lines if vertical overlap
       exceeds 45% of minimum block height.
    3. Sort grouped lines vertically by mean y coordinate.
    4. Within each line, sort words/blocks left-to-right (x_min ascending).
    5. Join words in a line with a single space, and lines with a newline.
    """
    if not blocks:
        return ""

    # Filter out empty blocks
    valid_blocks = [b for b in blocks if b.text.strip()]
    if not valid_blocks:
        return ""

    sorted_blocks = sorted(valid_blocks, key=lambda b: (b.y_min, b.x_min))
    lines: list[list[OcrTextBlock]] = []

    for b in sorted_blocks:
        placed = False
        for line in lines:
            line_y_min = min(lb.y_min for lb in line)
            line_y_max = max(lb.y_max for lb in line)
            line_h = max(1.0, line_y_max - line_y_min)
            overlap = min(b.y_max, line_y_max) - max(b.y_min, line_y_min)
            min_h = max(1.0, min(b.height, line_h))

            if overlap > 0 and (overlap / min_h) >= 0.45:
                line.append(b)
                placed = True
                break
        if not placed:
            lines.append([b])

    # Sort lines vertically from top to bottom
    lines.sort(key=lambda line: sum(b.y_min for b in line) / len(line))

    # Format each line horizontally left-to-right
    text_lines: list[str] = []
    for line in lines:
        line.sort(key=lambda b: b.x_min)
        line_str = " ".join(b.text.strip() for b in line if b.text.strip())
        if line_str:
            text_lines.append(line_str)

    return "\n".join(text_lines)


class RapidOcrEngine:
    """Local, offline OCR engine using RapidOCR and ONNX Runtime CPU.

    PP-OCRv4 detection and recognition models are bundled locally with zero
    telemetry, zero cloud dependencies, and zero runtime downloads.
    """

    _cached_instance: Optional[Any] = None

    @classmethod
    def is_available(cls) -> bool:
        """Check if rapidocr_onnxruntime is installed and importable."""
        try:
            import rapidocr_onnxruntime  # noqa: F401
            return True
        except ImportError:
            return False

    @classmethod
    def get_engine(cls) -> Any:
        """Return a reusable RapidOCR engine instance to avoid redundant ONNX allocations."""
        if cls._cached_instance is None:
            try:
                from rapidocr_onnxruntime import RapidOCR
                cls._cached_instance = RapidOCR(print_verbose=False)
            except Exception as exc:
                log.exception("Failed to initialize RapidOCR engine: %s", exc)
                raise RuntimeError(f"Could not initialize RapidOCR engine: {exc}") from exc
        return cls._cached_instance

    @classmethod
    def process_image(
        cls,
        image_data: Any,
        *,
        page_number: int = 1,
        min_confidence: float = 0.5,
    ) -> OcrPageResult:
        """Execute OCR on a raster image (numpy ndarray, PIL Image, or file path).

        Returns structured :class:`OcrPageResult` with detected blocks, mean confidence,
        and reconstructed reading order.
        """
        engine = cls.get_engine()

        # Convert PIL Image to numpy if provided
        if hasattr(image_data, "convert") and not hasattr(image_data, "shape"):
            import numpy as np
            image_arr = np.array(image_data.convert("RGB"))
        else:
            image_arr = image_data

        t0 = time.perf_counter()
        raw_result, elapse_list = engine(image_arr)
        duration_ms = (time.perf_counter() - t0) * 1000.0

        if not raw_result:
            return OcrPageResult(
                page_number=page_number,
                text="",
                blocks=(),
                mean_confidence=0.0,
                duration_ms=duration_ms,
                warnings=("No text detected by OCR engine on page.",),
            )

        blocks: list[OcrTextBlock] = []
        conf_sum = 0.0
        warnings: list[str] = []

        for idx, item in enumerate(raw_result):
            # item structure: [box_coordinates, text, score]
            box_coords = item[0]
            text = str(item[1])
            score = item[2]

            block = OcrTextBlock.from_raw_detection(
                box_coords,
                text,
                score,
                page_number=page_number,
                detection_order=idx,
            )
            blocks.append(block)
            conf_sum += block.confidence

        mean_conf = conf_sum / len(blocks) if blocks else 0.0

        if mean_conf < min_confidence and blocks:
            warnings.append(f"Low OCR recognition confidence ({mean_conf:.1%}). Text may contain errors.")

        reconstructed_text = reconstruct_reading_order(blocks)

        return OcrPageResult(
            page_number=page_number,
            text=reconstructed_text,
            blocks=tuple(blocks),
            mean_confidence=mean_conf,
            duration_ms=duration_ms,
            warnings=tuple(warnings),
        )
