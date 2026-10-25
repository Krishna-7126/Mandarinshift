"""
localshift.documents.ocr — Offline OCR engine foundation and reading-order reconstruction.

Integrates RapidOCR with ONNX Runtime CPU for fully local, privacy-first,
offline text recognition from scanned PDF pages and raster images.
"""
from __future__ import annotations

import logging
import sys
import time
from dataclasses import dataclass
from typing import Any, Optional, Sequence

log = logging.getLogger(__name__)



def normalize_ocr_text(text: str) -> str:
    """Normalize OCR text, converting full-width CJK punctuation/glyphs to standard ASCII.

    - Full-width ASCII variants (U+FF01 to U+FF5E) -> standard ASCII (U+0021 to U+007E).
    - Ideographic space (U+3000) -> standard space (U+0020).
    - Common OCR currency digit confusion: converts 'o'/'O' to '0' in amounts like '$o.0o'.
    """
    if not text:
        return ""

    chars: list[str] = []
    for c in text:
        code = ord(c)
        if 0xFF01 <= code <= 0xFF5E:
            chars.append(chr(code - 0xFEE0))
        elif code == 0x3000:
            chars.append(" ")
        else:
            chars.append(c)
    normalized = "".join(chars)

    # Clean up common OCR digit confusion in currency amounts: e.g. $o.0o -> $0.00
    import re

    def _fix_currency(match: re.Match[str]) -> str:
        symbol = match.group(1)
        int_part = match.group(2).replace("o", "0").replace("O", "0")
        dec_part = match.group(3).replace("o", "0").replace("O", "0")
        return f"{symbol}{int_part}.{dec_part}"

    normalized = re.sub(r"([$€£¥])([0-9oO]+)\.([0-9oO]+)", _fix_currency, normalized)
    return normalized


def preprocess_image_for_ocr(image: Any) -> Any:
    """Apply dynamic range contrast enhancement for faint or degraded scans.

    If dynamic range is compressed (< 180), applies PIL ImageOps.autocontrast.
    Leaves high-contrast clean documents untouched.
    """
    from PIL import Image, ImageOps
    import numpy as np

    if isinstance(image, np.ndarray):
        pil_img = Image.fromarray(image)
    elif hasattr(image, "convert"):
        pil_img = image
    else:
        return image

    gray = pil_img.convert("L")
    extrema = gray.getextrema()
    if extrema and (extrema[1] - extrema[0]) < 180:
        enhanced = ImageOps.autocontrast(gray, cutoff=0.5)
        return np.array(enhanced.convert("RGB"))

    if isinstance(image, np.ndarray):
        return image
    return np.array(pil_img.convert("RGB"))


@dataclass(frozen=True)
class LanguagePackConfig:
    """Configuration for an optional offline OCR language model pack."""
    language_code: str
    display_name: str
    rec_model_path: Optional[str] = None
    det_model_path: Optional[str] = None
    keys_path: Optional[str] = None
    description: str = ""


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
            text=normalize_ocr_text(str(text).strip()),
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
        line_str = " ".join(normalize_ocr_text(b.text.strip()) for b in line if b.text.strip())
        if line_str:
            text_lines.append(line_str)

    return "\n".join(text_lines)


class RapidOcrEngine:
    """Local, offline OCR engine using RapidOCR and ONNX Runtime CPU.

    PP-OCRv3 detection and recognition models are bundled locally with zero
    telemetry, zero cloud dependencies, and zero runtime downloads.
    """

    _cached_instances: dict[str, Any] = {}
    _registered_language_packs: dict[str, LanguagePackConfig] = {}

    @classmethod
    def is_available(cls) -> bool:
        """Check if rapidocr_onnxruntime is installed and importable."""
        try:
            import rapidocr_onnxruntime  # noqa: F401
            return True
        except ImportError:
            return False

    @classmethod
    def register_language_pack(cls, pack: LanguagePackConfig) -> None:
        """Register an offline language pack configuration.

        Enables pointing to locally downloaded ONNX models and character dictionaries
        without any network access or runtime downloads.
        """
        key = pack.language_code.lower().strip()
        cls._registered_language_packs[key] = pack
        cls._cached_instances.pop(key, None)

    @classmethod
    def get_supported_languages(cls) -> tuple[str, ...]:
        """Return tuple of supported language codes (bundled + registered packs)."""
        base = ["en", "ch"]
        custom = [k for k in cls._registered_language_packs if k not in base]
        return tuple(base + custom)

    @classmethod
    def is_language_supported(cls, lang_code: Optional[str]) -> bool:
        """Check if a language code is currently supported by bundled or registered models."""
        if not lang_code:
            return True
        code = lang_code.strip().lower()
        if code in ("en", "english", "ch", "chinese", "zh", "default"):
            return True
        return code in cls._registered_language_packs

    @classmethod
    def get_engine(cls, language: Optional[str] = None) -> Any:
        """Return a reusable RapidOCR engine instance for the requested language."""
        lang_key = (language or "default").strip().lower()
        if lang_key in ("en", "english", "ch", "chinese", "zh"):
            lang_key = "default"

        if lang_key in cls._cached_instances:
            return cls._cached_instances[lang_key]

        try:
            # RapidOCR dynamically imports 'ch_ppocr_v3_det', 'ch_ppocr_v3_rec', and
            # 'ch_ppocr_v2_cls' via importlib. In PyInstaller frozen bundles, these
            # reside under 'rapidocr_onnxruntime.<submodule>'. Register top-level aliases.
            try:
                import rapidocr_onnxruntime.ch_ppocr_v2_cls as _cls
                import rapidocr_onnxruntime.ch_ppocr_v3_det as _det
                import rapidocr_onnxruntime.ch_ppocr_v3_rec as _rec

                sys.modules.setdefault("ch_ppocr_v2_cls", _cls)
                sys.modules.setdefault("ch_ppocr_v3_det", _det)
                sys.modules.setdefault("ch_ppocr_v3_rec", _rec)
            except ImportError:
                pass

            from rapidocr_onnxruntime import RapidOCR

            if lang_key in cls._registered_language_packs:
                pack = cls._registered_language_packs[lang_key]
                kwargs: dict[str, Any] = {"print_verbose": False}
                rec_cfg: dict[str, Any] = {}
                if pack.rec_model_path:
                    rec_cfg["model_path"] = pack.rec_model_path
                if pack.keys_path:
                    rec_cfg["keys_path"] = pack.keys_path
                if rec_cfg:
                    kwargs["Rec"] = rec_cfg
                if pack.det_model_path:
                    kwargs["Det"] = {"model_path": pack.det_model_path}
                instance = RapidOCR(**kwargs)
            else:
                instance = RapidOCR(print_verbose=False)

            cls._cached_instances[lang_key] = instance
            return instance
        except Exception as exc:
            log.exception("Failed to initialize RapidOCR engine: %s", exc)
            raise RuntimeError(f"Could not initialize RapidOCR engine: {exc}") from exc

    @classmethod
    def process_image(
        cls,
        image_data: Any,
        *,
        page_number: int = 1,
        min_confidence: float = 0.5,
        language: Optional[str] = None,
        correct_orientation: bool = True,
        preprocess: bool = True,
    ) -> OcrPageResult:
        """Execute OCR on a raster image (numpy ndarray, PIL Image, or file path).

        Returns structured :class:`OcrPageResult` with detected blocks, mean confidence,
        and reconstructed reading order.
        """
        import numpy as np

        engine = cls.get_engine(language)
        warnings: list[str] = []

        if language and not cls.is_language_supported(language):
            warnings.append(
                f"OCR language '{language}' is not supported by the default bundled model "
                f"(which supports English and Chinese). Register an offline language pack "
                f"via RapidOcrEngine.register_language_pack() to enable '{language}' recognition."
            )

        # Convert PIL Image to numpy array if provided
        if hasattr(image_data, "convert") and not hasattr(image_data, "shape"):
            image_arr = np.array(image_data.convert("RGB"))
        else:
            image_arr = np.asarray(image_data)

        if preprocess:
            image_arr = preprocess_image_for_ocr(image_arr)

        t0 = time.perf_counter()
        raw_result, elapse_list = engine(image_arr)

        # Automatic orientation recovery:
        # 1. 180° upside-down recovery: RapidOCR flips individual chips for recognition,
        # but leaves bounding box coordinates upside-down, reversing reading order.
        # If >50% of crops are classified as 180°, rotate the entire image 180°.
        if correct_orientation and raw_result:
            try:
                boxes_np = [np.array(item[0], dtype=np.float32) for item in raw_result]
                crops = engine.get_crop_img_list(image_arr, boxes_np)
                _, cls_res, _ = engine.text_cls(crops)
                inverted_180 = sum(1 for c in cls_res if c[0] == "180" and float(c[1]) > 0.8)
                if inverted_180 > len(cls_res) * 0.5:
                    arr_180 = np.rot90(image_arr, 2)
                    res_180, _ = engine(arr_180)
                    if res_180:
                        raw_result = res_180
                        image_arr = arr_180
                        warnings.append("Upside-down page scan detected; automatically corrected orientation (rotated 180°).")
            except Exception:
                pass

        # 2. 90°/270° sideways recovery:
        # If >50% of detected boxes are predominantly vertical (height > 1.2 * width),
        # the scan is oriented sideways.
        if correct_orientation and raw_result:
            vert_count = sum(
                1 for item in raw_result
                if (max(p[1] for p in item[0]) - min(p[1] for p in item[0]))
                > 1.2 * max(1.0, (max(p[0] for p in item[0]) - min(p[0] for p in item[0])))
            )
            if vert_count > len(raw_result) * 0.5:
                # Test 270° (rot90 3x) and verify angle classification
                arr_270 = np.rot90(image_arr, 3)
                try:
                    boxes_270, _ = engine.text_detector(arr_270)
                    boxes_270 = engine.sorted_boxes(boxes_270)
                    crops_270 = engine.get_crop_img_list(arr_270, boxes_270)
                    _, cls_270, _ = engine.text_cls(crops_270)
                    upright_270 = sum(1 for c in cls_270 if c[0] == "0")
                except Exception:
                    upright_270 = 0
                    cls_270 = []

                if upright_270 >= (len(cls_270) / 2):
                    res_270, _ = engine(arr_270)
                    if res_270:
                        raw_result = res_270
                        image_arr = arr_270
                        warnings.append("Sideways page scan detected; automatically corrected orientation (rotated 270°).")
                else:
                    arr_90 = np.rot90(image_arr, 1)
                    res_90, _ = engine(arr_90)
                    if res_90:
                        raw_result = res_90
                        image_arr = arr_90
                        warnings.append("Sideways page scan detected; automatically corrected orientation (rotated 90°).")

        duration_ms = (time.perf_counter() - t0) * 1000.0

        if not raw_result:
            return OcrPageResult(
                page_number=page_number,
                text="",
                blocks=(),
                mean_confidence=0.0,
                duration_ms=duration_ms,
                warnings=tuple(warnings) + ("No text detected by OCR engine on page.",),
            )

        blocks: list[OcrTextBlock] = []
        conf_sum = 0.0

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

        # Check for Devanagari script presence without a configured Hindi pack
        if any("\u0900" <= c <= "\u097f" for c in reconstructed_text) and not cls.is_language_supported("hi"):
            warnings.append(
                "Devanagari characters detected, but the active OCR model pack does not support Hindi. "
                "Register an offline Hindi model pack for accurate recognition."
            )

        return OcrPageResult(
            page_number=page_number,
            text=reconstructed_text,
            blocks=tuple(blocks),
            mean_confidence=mean_conf,
            duration_ms=duration_ms,
            warnings=tuple(warnings),
        )
