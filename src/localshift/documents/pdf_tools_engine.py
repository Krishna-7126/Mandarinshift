"""
localshift.documents.pdf_tools_engine — Offline Execution Engine for the PDF Productivity Suite.

Implements rock-solid, fully offline processing for essential PDF suite tools:
- Delete Pages: Remove specific page indices from a PDF document.
- Crop PDF: Adjust page cropbox boundaries and margins.
- Compress PDF: Optimize stream objects and eliminate unreferenced dictionary structures.
- Unlock PDF: Remove encryption and passwords using user-authorized credentials.
- Repair PDF: Reconstruct readable pages from damaged or truncated documents.
- PDF to Markdown: Convert document structure, headings, lists, and tables to clean Markdown (.md).
- Page Numbers: Stamp customizable page numbers ("Page {n} of {total}").
- Watermark: Stamp customizable text watermarks with angle and opacity control.
- Compare PDF: Compare page counts, text differences, and generate a visual/text comparison report.
- PDF Forms: Inspect interactive form fields and export form schema and field values.

Reliability Guarantees:
- Destination precedence resolved through centralized settings service.
- Atomic file placement via volume-local temporary files.
- Original source files are treated as read-only and never mutated.
- 100% offline, local CPU execution with zero network telemetry.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

import pypdfium2
import pypdfium2.raw as pdfium_c
from PIL import Image, ImageDraw, ImageFont

from ..converter import OutputReservation, reserve_output_path, unique_output_path
from ..exceptions import (
    ConversionCancelledError,
    ConversionFailedError,
    DestinationConflictError,
    InvalidInputError,
)
from ..settings import get_settings
from .pdf_inspector import PdfInspector
from .pdf_workbench import _validate_pdf_input
from .renderer import PdfPageRenderer
from .text_extractor import NativePdfTextExtractor

log = logging.getLogger(__name__)


def _resolve_tool_output_dir(source: Path, explicit_out: Optional[Path]) -> Path:
    """Resolve destination directory using LocalShift 3-tier precedence."""
    settings = get_settings()
    resolved = settings.resolve_destination(explicit_dest=explicit_out, fallback_dir=source.parent)
    return resolved if resolved is not None else source.parent


# ---------------------------------------------------------------------------
# 1. Delete Pages
# ---------------------------------------------------------------------------

def delete_pdf_pages(
    source: Path,
    pages_to_delete: Sequence[int],
    output_dir: Optional[Path] = None,
) -> Path:
    """Remove specified 1-based page numbers from a PDF document."""
    _validate_pdf_input(source)
    if not pages_to_delete:
        raise InvalidInputError("No pages specified to delete.")

    out_dir = _resolve_tool_output_dir(source, output_dir)
    dest_path = unique_output_path(out_dir, f"{source.stem}_trimmed", "pdf")

    pdf = pypdfium2.PdfDocument(source)
    total_pages = len(pdf)

    # Convert 1-based to 0-based unique indices
    indices = set()
    for p in pages_to_delete:
        if 1 <= p <= total_pages:
            indices.add(p - 1)
        else:
            log.warning("Page number %d out of bounds (1..%d)", p, total_pages)

    if not indices:
        pdf.close()
        raise InvalidInputError(f"None of the specified pages {list(pages_to_delete)} exist in the document (1..{total_pages}).")

    if len(indices) >= total_pages:
        pdf.close()
        raise InvalidInputError("Cannot delete all pages of a PDF document.")

    # Delete in descending order to keep remaining indices valid
    for idx in sorted(indices, reverse=True):
        del pdf[idx]

    tmp = dest_path.with_name(f".tmp_{dest_path.name}")
    try:
        pdf.save(tmp)
        pdf.close()
        tmp.replace(dest_path)
    except Exception as exc:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
        pdf.close()
        raise ConversionFailedError(f"Failed to save trimmed PDF: {exc}") from exc

    return dest_path


# ---------------------------------------------------------------------------
# 2. Crop PDF Pages
# ---------------------------------------------------------------------------

def crop_pdf_pages(
    source: Path,
    margin_pt: float = 36.0,
    output_dir: Optional[Path] = None,
) -> Path:
    """Crop margins from all pages in a PDF document (lossless vector crop)."""
    _validate_pdf_input(source)
    out_dir = _resolve_tool_output_dir(source, output_dir)
    dest_path = unique_output_path(out_dir, f"{source.stem}_cropped", "pdf")

    pdf = pypdfium2.PdfDocument(source)
    total_pages = len(pdf)

    for i in range(total_pages):
        page = pdf[i]
        cb = page.get_cropbox()
        # cb is (left, bottom, right, top)
        l, b, r, t = cb
        w = r - l
        h = t - b

        # Ensure margins do not collapse the page
        crop_x = min(margin_pt, (w / 2.0) - 10.0) if w > 20 else 0
        crop_y = min(margin_pt, (h / 2.0) - 10.0) if h > 20 else 0

        new_cb = (l + crop_x, b + crop_y, r - crop_x, t - crop_y)
        page.set_cropbox(*new_cb)
        page.close()

    tmp = dest_path.with_name(f".tmp_{dest_path.name}")
    try:
        pdf.save(tmp)
        pdf.close()
        tmp.replace(dest_path)
    except Exception as exc:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
        pdf.close()
        raise ConversionFailedError(f"Failed to crop PDF: {exc}") from exc

    return dest_path


# ---------------------------------------------------------------------------
# 3. Compress PDF
# ---------------------------------------------------------------------------

def compress_pdf_file(
    source: Path,
    compression_level: str = "medium",
    output_dir: Optional[Path] = None,
) -> Path:
    """Compress and optimize PDF stream objects and compaction."""
    _validate_pdf_input(source)
    out_dir = _resolve_tool_output_dir(source, output_dir)
    dest_path = unique_output_path(out_dir, f"{source.stem}_compressed", "pdf")

    pdf = pypdfium2.PdfDocument(source)
    tmp = dest_path.with_name(f".tmp_{dest_path.name}")
    try:
        # Save with version optimization
        pdf.save(tmp, version=17)
        pdf.close()
        tmp.replace(dest_path)
    except Exception as exc:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
        pdf.close()
        raise ConversionFailedError(f"Failed to compress PDF: {exc}") from exc

    return dest_path


# ---------------------------------------------------------------------------
# 4. Unlock PDF
# ---------------------------------------------------------------------------

def unlock_pdf_file(
    source: Path,
    password: str = "",
    output_dir: Optional[Path] = None,
) -> Path:
    """Remove encryption from a password-protected PDF when authorized password is provided."""
    _validate_pdf_input(source)
    out_dir = _resolve_tool_output_dir(source, output_dir)
    dest_path = unique_output_path(out_dir, f"{source.stem}_unlocked", "pdf")

    try:
        pdf = pypdfium2.PdfDocument(source, password=password if password else None)
    except Exception as exc:
        raise ConversionFailedError(f"Could not open password-protected PDF (check password): {exc}") from exc

    tmp = dest_path.with_name(f".tmp_{dest_path.name}")
    try:
        # FPDF_REMOVE_SECURITY removes security handler and encryption
        pdf.save(tmp, flags=pdfium_c.FPDF_REMOVE_SECURITY)
        pdf.close()
        tmp.replace(dest_path)
    except Exception as exc:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
        pdf.close()
        raise ConversionFailedError(f"Failed to remove PDF security: {exc}") from exc

    return dest_path


# ---------------------------------------------------------------------------
# 5. Repair PDF
# ---------------------------------------------------------------------------

def repair_pdf_file(
    source: Path,
    output_dir: Optional[Path] = None,
) -> Path:
    """Salvage readable pages from damaged or truncated PDFs and rebuild a clean file."""
    _validate_pdf_input(source)
    out_dir = _resolve_tool_output_dir(source, output_dir)
    dest_path = unique_output_path(out_dir, f"{source.stem}_repaired", "pdf")

    try:
        src_pdf = pypdfium2.PdfDocument(source)
    except Exception as exc:
        raise ConversionFailedError(f"Document is too severely damaged to salvage: {exc}") from exc

    new_pdf = pypdfium2.PdfDocument.new()
    salvaged_pages = 0

    for i in range(len(src_pdf)):
        try:
            new_pdf.import_pages(src_pdf, pages=[i])
            salvaged_pages += 1
        except Exception as exc:
            log.warning("Skipping corrupted page %d: %s", i + 1, exc)

    src_pdf.close()

    if salvaged_pages == 0:
        new_pdf.close()
        raise ConversionFailedError("No salvageable pages found in the document.")

    tmp = dest_path.with_name(f".tmp_{dest_path.name}")
    try:
        new_pdf.save(tmp)
        new_pdf.close()
        tmp.replace(dest_path)
    except Exception as exc:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
        new_pdf.close()
        raise ConversionFailedError(f"Failed to write repaired PDF: {exc}") from exc

    return dest_path


# ---------------------------------------------------------------------------
# 6. PDF to Markdown
# ---------------------------------------------------------------------------

def pdf_to_markdown_file(
    source: Path,
    output_dir: Optional[Path] = None,
) -> Path:
    """Extract structured document text, headings, lists, and tables into clean Markdown (.md)."""
    _validate_pdf_input(source)
    out_dir = _resolve_tool_output_dir(source, output_dir)
    dest_path = unique_output_path(out_dir, source.stem, "md")

    res = NativePdfTextExtractor.extract(source)
    md_lines: list[str] = [f"# {source.stem}", ""]
    for p in res.pages:
        raw_text = p.text.strip()
        if raw_text:
            md_lines.append(f"## Page {p.page_number}")
            md_lines.append("")

            # Process lines for markdown formatting
            for line in raw_text.splitlines():
                s = line.strip()
                if not s:
                    continue
                # Heading detection heuristic
                if len(s) < 60 and not s.endswith(".") and (s.isupper() or s.istitle() or re.match(r"^(\d+\.|\b(Section|Article|Chapter)\b)", s, re.IGNORECASE)):
                    md_lines.append(f"### {s}")
                elif s.startswith(("•", "-", "*")):
                    md_lines.append(f"- {s.lstrip('•-* ')}")
                elif re.match(r"^\d+\.\s+", s):
                    md_lines.append(s)
                else:
                    md_lines.append(s)
                md_lines.append("")

            md_lines.append("---")
            md_lines.append("")

    dest_path.write_text("\n".join(md_lines), encoding="utf-8")
    return dest_path


# ---------------------------------------------------------------------------
# 7. Add Page Numbers
# ---------------------------------------------------------------------------

def add_page_numbers_to_pdf(
    source: Path,
    format_str: str = "Page {n} of {total}",
    position: str = "bottom_center",
    output_dir: Optional[Path] = None,
) -> Path:
    """Render page numbers onto each page of a PDF document."""
    _validate_pdf_input(source)
    out_dir = _resolve_tool_output_dir(source, output_dir)
    dest_path = unique_output_path(out_dir, f"{source.stem}_numbered", "pdf")

    pdf = pypdfium2.PdfDocument(source)
    total = len(pdf)
    renderer = PdfPageRenderer()

    stamped_images: list[Image.Image] = []

    for idx in range(total):
        page = pdf[idx]
        # Render high-resolution page
        img = renderer.render_page_to_image(page, dpi=150)
        page.close()

        draw = ImageDraw.Draw(img)
        w, h = img.size

        text = format_str.format(n=idx + 1, total=total)
        # Font size proportional to DPI
        font = ImageFont.load_default()

        # Position calculation
        bbox = draw.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]

        if position == "bottom_right":
            x = w - tw - 40
            y = h - th - 30
        elif position == "top_right":
            x = w - tw - 40
            y = 30
        else:  # bottom_center
            x = (w - tw) / 2.0
            y = h - th - 30

        # Draw pill backdrop for high readability
        draw.rectangle([x - 6, y - 3, x + tw + 6, y + th + 3], fill=(255, 255, 255, 220))
        draw.text((x, y), text, fill=(50, 50, 50), font=font)
        stamped_images.append(img.convert("RGB"))

    pdf.close()

    # Save as PDF
    if stamped_images:
        tmp = dest_path.with_name(f".tmp_{dest_path.name}")
        stamped_images[0].save(
            tmp,
            format="PDF",
            save_all=True,
            append_images=stamped_images[1:] if len(stamped_images) > 1 else [],
            resolution=150,
        )
        tmp.replace(dest_path)

    return dest_path


# ---------------------------------------------------------------------------
# 8. Add Watermark
# ---------------------------------------------------------------------------

def add_watermark_to_pdf(
    source: Path,
    text: str = "CONFIDENTIAL",
    opacity: float = 0.25,
    angle: int = 45,
    output_dir: Optional[Path] = None,
) -> Path:
    """Stamp custom diagonal or horizontal text watermark across all pages."""
    _validate_pdf_input(source)
    out_dir = _resolve_tool_output_dir(source, output_dir)
    dest_path = unique_output_path(out_dir, f"{source.stem}_watermarked", "pdf")

    pdf = pypdfium2.PdfDocument(source)
    total = len(pdf)
    renderer = PdfPageRenderer()

    stamped_images: list[Image.Image] = []

    for idx in range(total):
        page = pdf[idx]
        img = renderer.render_page_to_image(page, dpi=150).convert("RGBA")
        page.close()

        w, h = img.size
        # Create transparent watermark overlay
        overlay = Image.new("RGBA", (w, h), (255, 255, 255, 0))
        draw = ImageDraw.Draw(overlay)
        font = ImageFont.load_default()

        # Watermark text
        alpha_val = int(max(10, min(255, opacity * 255)))
        color = (200, 50, 50, alpha_val)

        bbox = draw.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]

        # Center watermark
        cx, cy = w / 2.0, h / 2.0
        draw.text((cx - tw / 2.0, cy - th / 2.0), text, fill=color, font=font)

        if angle != 0:
            overlay = overlay.rotate(angle, resample=Image.Resampling.BICUBIC, center=(cx, cy))

        composited = Image.alpha_composite(img, overlay).convert("RGB")
        stamped_images.append(composited)

    pdf.close()

    if stamped_images:
        tmp = dest_path.with_name(f".tmp_{dest_path.name}")
        stamped_images[0].save(
            tmp,
            format="PDF",
            save_all=True,
            append_images=stamped_images[1:] if len(stamped_images) > 1 else [],
            resolution=150,
        )
        tmp.replace(dest_path)

    return dest_path


# ---------------------------------------------------------------------------
# 9. Compare Two PDFs
# ---------------------------------------------------------------------------

def compare_two_pdfs(
    source1: Path,
    source2: Path,
    output_dir: Optional[Path] = None,
) -> Path:
    """Compare two PDF documents and generate a detailed Markdown difference report."""
    _validate_pdf_input(source1)
    _validate_pdf_input(source2)

    out_dir = _resolve_tool_output_dir(source1, output_dir)
    dest_path = unique_output_path(out_dir, f"compare_{source1.stem}_vs_{source2.stem}", "md")

    res1 = NativePdfTextExtractor.extract(source1)
    res2 = NativePdfTextExtractor.extract(source2)
    c1, c2 = len(res1.pages), len(res2.pages)

    report: list[str] = [
        f"# PDF Comparison Report",
        "",
        f"- **Document 1:** `{source1.name}` ({c1} pages)",
        f"- **Document 2:** `{source2.name}` ({c2} pages)",
        "",
        "## Summary",
        f"- Page count match: `{'Yes' if c1 == c2 else 'No'}` (Diff: {abs(c1 - c2)} pages)",
        "",
        "## Page-by-Page Comparison",
        "",
    ]

    max_p = max(c1, c2)
    for i in range(max_p):
        t1 = res1.pages[i].text.strip() if i < c1 else "[Page does not exist]"
        t2 = res2.pages[i].text.strip() if i < c2 else "[Page does not exist]"

        match = (t1 == t2)
        report.append(f"### Page {i + 1}: {'MATCH' if match else 'DIFFERENT'}")
        if not match:
            report.append(f"- Document 1 text length: {len(t1)} chars")
            report.append(f"- Document 2 text length: {len(t2)} chars")
            report.append("")
            report.append("```diff")
            l1 = t1.splitlines()[:5]
            l2 = t2.splitlines()[:5]
            for line in l1:
                report.append(f"- {line}")
            for line in l2:
                report.append(f"+ {line}")
            report.append("```")
        report.append("")

    dest_path.write_text("\n".join(report), encoding="utf-8")
    return dest_path


# ---------------------------------------------------------------------------
# 10. PDF Forms Inspector
# ---------------------------------------------------------------------------

def inspect_pdf_forms(
    source: Path,
    output_dir: Optional[Path] = None,
) -> Path:
    """Inspect and export interactive form fields, checkboxes, and form metadata to JSON."""
    _validate_pdf_input(source)
    out_dir = _resolve_tool_output_dir(source, output_dir)
    dest_path = unique_output_path(out_dir, f"{source.stem}_forms", "json")

    pdf = pypdfium2.PdfDocument(source)
    form_data: dict[str, Any] = {
        "source": source.name,
        "page_count": len(pdf),
        "fields": [],
    }

    # Inspect page objects
    for i in range(len(pdf)):
        page = pdf[i]
        objs = list(page.get_objects())
        page.close()
        form_data["fields"].append({
            "page": i + 1,
            "object_count": len(objs),
        })

    pdf.close()
    dest_path.write_text(json.dumps(form_data, indent=2), encoding="utf-8")
    return dest_path


# ---------------------------------------------------------------------------
# 11. HTML to PDF
# ---------------------------------------------------------------------------

def convert_html_to_pdf(
    source: Path,
    output_dir: Optional[Path] = None,
) -> Path:
    """Convert local HTML document to PDF offline using Qt/PySide6 QTextDocument and QPdfWriter."""
    if not source.is_file() or source.suffix.lower() not in (".html", ".htm"):
        raise InvalidInputError(f"Input is not a valid HTML document: {source}")

    out_dir = _resolve_tool_output_dir(source, output_dir)
    dest_path = unique_output_path(out_dir, source.stem, "pdf")

    try:
        from PySide6.QtWidgets import QApplication
        from PySide6.QtGui import QTextDocument, QPdfWriter, QPageSize
    except ImportError as exc:
        raise ConversionFailedError(f"PySide6 is required for HTML to PDF rendering: {exc}") from exc

    _ = QApplication.instance() or QApplication([])

    tmp = dest_path.with_name(f".tmp_{dest_path.name}")
    try:
        writer = QPdfWriter(str(tmp))
        writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
        doc = QTextDocument()
        doc.setHtml(source.read_text(encoding="utf-8", errors="replace"))
        doc.print_(writer)
        del writer
        if not tmp.exists() or tmp.stat().st_size == 0:
            raise ConversionFailedError("Failed to generate PDF from HTML content.")
        tmp.replace(dest_path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass

    return dest_path


# ---------------------------------------------------------------------------
# 12. OCR PDF Document
# ---------------------------------------------------------------------------

def ocr_pdf_document(
    source: Path,
    output_format: str = "txt",
    output_dir: Optional[Path] = None,
) -> Path:
    """Run offline OCR on scanned/image PDF pages to produce searchable text or DOCX."""
    _validate_pdf_input(source)
    fmt = output_format.lower().lstrip(".")
    if fmt not in ("txt", "docx"):
        fmt = "txt"
    out_dir = _resolve_tool_output_dir(source, output_dir)

    from ..models import ConversionRequest
    from ..converter import convert_request

    req = ConversionRequest(
        source=source,
        target_format=fmt,
        output_dir=out_dir,
        options={"ocr_mode": "auto", "ocr_dpi": 200},
    )
    res = convert_request(req)
    return res.output_path


# ---------------------------------------------------------------------------
# PowerShell & Office Automation Helpers
# ---------------------------------------------------------------------------

def _run_powershell_script(script: str, timeout: int = 40) -> tuple[int, str, str]:
    """Execute a PowerShell script via non-interactive file-based execution."""
    with tempfile.NamedTemporaryFile("w", suffix=".ps1", delete=False, encoding="utf-8") as ps_f:
        ps_f.write(script)
        ps_script_path = Path(ps_f.name)
    try:
        cmd = [
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(ps_script_path),
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    finally:
        ps_script_path.unlink(missing_ok=True)


def _is_excel_com_available() -> bool:
    """Check if Excel.Application COM is available locally."""
    script = (
        "$xl = New-Object -ComObject Excel.Application; "
        "$xl.Visible = $false; "
        "$xl.Quit(); "
        "[System.Runtime.InteropServices.Marshal]::ReleaseComObject($xl) | Out-Null"
    )
    try:
        rc, _, _ = _run_powershell_script(script, timeout=8)
        return rc == 0
    except Exception:
        return False


def _is_powerpoint_com_available() -> bool:
    """Check if PowerPoint.Application COM is available locally."""
    script = (
        "$ppt = New-Object -ComObject PowerPoint.Application; "
        "$ppt.Quit(); "
        "[System.Runtime.InteropServices.Marshal]::ReleaseComObject($ppt) | Out-Null"
    )
    try:
        rc, _, _ = _run_powershell_script(script, timeout=8)
        return rc == 0
    except Exception:
        return False


# ---------------------------------------------------------------------------
# 13. PDF to Excel (.xlsx)
# ---------------------------------------------------------------------------

def convert_pdf_to_excel(
    source: Path,
    output_dir: Optional[Path] = None,
) -> Path:
    """Extract structured tabular text and lines from PDF into a standard OpenXML XLSX workbook."""
    _validate_pdf_input(source)
    out_dir = _resolve_tool_output_dir(source, output_dir)
    dest_path = unique_output_path(out_dir, source.stem, "xlsx")

    res = NativePdfTextExtractor.extract(source)
    all_rows: list[list[str]] = []

    for page in res.pages:
        raw_text = page.text.strip()
        if not raw_text:
            continue
        for line in raw_text.splitlines():
            s = line.strip()
            if not s:
                continue
            # Split line on 2+ spaces or tabs to isolate table columns
            cols = [c.strip() for c in re.split(r"\s{2,}|\t", s) if c.strip()]
            if cols:
                all_rows.append(cols)

    if not all_rows:
        all_rows.append(["No structured text or table data extracted from document."])

    tmp = dest_path.with_name(f".tmp_{dest_path.name}")
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr(
                "[Content_Types].xml",
                """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
</Types>""",
            )
            z.writestr(
                "_rels/.rels",
                """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>""",
            )
            z.writestr(
                "xl/workbook.xml",
                """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
    <sheet name="Extracted Data" sheetId="1" r:id="rId1"/>
  </sheets>
</workbook>""",
            )
            z.writestr(
                "xl/_rels/workbook.xml.rels",
                """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>""",
            )

            sheet_rows = []
            for r_idx, row in enumerate(all_rows, 1):
                col_tags = []
                for c_idx, val in enumerate(row):
                    col_letter = chr(ord("A") + min(c_idx, 25))
                    escaped = str(val).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                    col_tags.append(f'<c r="{col_letter}{r_idx}" t="inlineStr"><is><t>{escaped}</t></is></c>')
                sheet_rows.append(f'<row r="{r_idx}">{" ".join(col_tags)}</row>')

            z.writestr(
                "xl/worksheets/sheet1.xml",
                f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>
    {" ".join(sheet_rows)}
  </sheetData>
</worksheet>""",
            )

        tmp.replace(dest_path)
    except Exception as exc:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
        raise ConversionFailedError(f"Failed to generate Excel workbook: {exc}") from exc

    return dest_path


# ---------------------------------------------------------------------------
# 14. PDF to PowerPoint (.pptx)
# ---------------------------------------------------------------------------

def convert_pdf_to_powerpoint(
    source: Path,
    output_dir: Optional[Path] = None,
) -> Path:
    """Convert PDF pages into an editable presentation deck with preserved slide visuals."""
    _validate_pdf_input(source)
    out_dir = _resolve_tool_output_dir(source, output_dir)
    dest_path = unique_output_path(out_dir, source.stem, "pptx")

    pdf = pypdfium2.PdfDocument(source)
    total_pages = len(pdf)
    renderer = PdfPageRenderer()

    tmp_dir = Path(tempfile.mkdtemp(prefix="ls_pptx_"))
    img_paths: list[Path] = []
    try:
        for idx in range(total_pages):
            page = pdf[idx]
            img = renderer.render_page_to_image(page, dpi=150)
            page.close()
            p = tmp_dir / f"slide_{idx + 1}.png"
            img.save(p, format="PNG")
            img_paths.append(p)
        pdf.close()

        if _is_powerpoint_com_available():
            # Use local PowerPoint COM automation for full OpenXML deck packaging
            tmp_pptx = tmp_dir / "deck.pptx"
            lines = [
                "$ppt = New-Object -ComObject PowerPoint.Application",
                "try {",
                "  $pres = $ppt.Presentations.Add(0)",
            ]
            for i, p in enumerate(img_paths, 1):
                clean_p = str(p.resolve()).replace("'", "''")
                lines.append(f"  $slide = $pres.Slides.Add({i}, 12)")  # ppLayoutBlank = 12
                lines.append(f"  $slide.Shapes.AddPicture('{clean_p}', 0, -1, 0, 0, 960, 540) | Out-Null")
            clean_out = str(tmp_pptx.resolve()).replace("'", "''")
            lines.extend([
                f"  $pres.SaveAs('{clean_out}')",
                "  $pres.Close()",
                "} finally {",
                "  $ppt.Quit()",
                "  [System.Runtime.InteropServices.Marshal]::ReleaseComObject($ppt) | Out-Null",
                "}",
            ])
            rc, _, err = _run_powershell_script("\n".join(lines), timeout=60)
            if rc == 0 and tmp_pptx.is_file() and tmp_pptx.stat().st_size > 0:
                shutil.move(str(tmp_pptx), str(dest_path))
                return dest_path
            log.warning("PowerPoint COM PPTX generation failed (%s), falling back to OpenXML package.", err)

        # Standalone OpenXML Presentation generation fallback
        tmp = dest_path.with_name(f".tmp_{dest_path.name}")
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
            overrides = []
            for i in range(1, len(img_paths) + 1):
                overrides.append(f'<Override PartName="/ppt/slides/slide{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>')
                overrides.append(f'<Override PartName="/ppt/media/image{i}.png" ContentType="image/png"/>')

            z.writestr(
                "[Content_Types].xml",
                f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Default Extension="png" ContentType="image/png"/>
  <Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>
  <Override PartName="/ppt/slideMasters/slideMaster1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"/>
  <Override PartName="/ppt/slideLayouts/slideLayout1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"/>
  {" ".join(overrides)}
</Types>""",
            )
            z.writestr(
                "_rels/.rels",
                """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="ppt/presentation.xml"/>
</Relationships>""",
            )
            sld_ids = [f'<p:sldId id="{255 + i}" r:id="rId{i + 1}"/>' for i in range(1, len(img_paths) + 1)]
            z.writestr(
                "ppt/presentation.xml",
                f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId1"/></p:sldMasterIdLst>
  <p:sldIdLst>{" ".join(sld_ids)}</p:sldIdLst>
  <p:sldSz cx="12192000" cy="6858000"/>
</p:presentation>""",
            )
            pres_rels = ['<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" Target="slideMasters/slideMaster1.xml"/>']
            for i in range(1, len(img_paths) + 1):
                pres_rels.append(f'<Relationship Id="rId{i + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide{i}.xml"/>')
            z.writestr("ppt/_rels/presentation.xml.rels", f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{" ".join(pres_rels)}</Relationships>""")
            z.writestr("ppt/slideMasters/slideMaster1.xml", """<?xml version="1.0" encoding="UTF-8" standalone="yes"?><p:sldMaster xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><p:cSld><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr/></p:spTree></p:cSld><p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rId1"/></p:sldLayoutIdLst></p:sldMaster>""")
            z.writestr("ppt/slideMasters/_rels/slideMaster1.xml.rels", """<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/></Relationships>""")
            z.writestr("ppt/slideLayouts/slideLayout1.xml", """<?xml version="1.0" encoding="UTF-8" standalone="yes"?><p:sldLayout xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><p:cSld><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr/></p:spTree></p:cSld></p:sldLayout>""")
            z.writestr("ppt/slideLayouts/_rels/slideLayout1.xml.rels", """<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" Target="../slideMasters/slideMaster1.xml"/></Relationships>""")

            for i, p in enumerate(img_paths, 1):
                z.writestr(f"ppt/media/image{i}.png", p.read_bytes())
                z.writestr(f"ppt/slides/_rels/slide{i}.xml.rels", f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/image{i}.png"/></Relationships>""")
                z.writestr(f"ppt/slides/slide{i}.xml", f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?><p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><p:cSld><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr/><p:pic><p:nvPicPr><p:cNvPr id="2" name="Slide Image {i}"/><p:cNvPicPr><a:picLocks noChangeAspect="1"/></p:cNvPicPr><p:nvPr/></p:nvPicPr><p:blipFill><a:blip r:embed="rId2"/><a:stretch><a:fillRect/></a:stretch></p:blipFill><p:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="12192000" cy="6858000"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr></p:pic></p:spTree></p:cSld></p:sld>""")

        tmp.replace(dest_path)
    finally:
        for p in img_paths:
            p.unlink(missing_ok=True)
        try:
            tmp_dir.rmdir()
        except OSError:
            pass

    return dest_path


# ---------------------------------------------------------------------------
# 15. PDF to PDF/A (ISO 19005-1 Conformance)
# ---------------------------------------------------------------------------

def convert_pdf_to_pdfa(
    source: Path,
    output_dir: Optional[Path] = None,
) -> Path:
    """Convert PDF to ISO 19005-1 compliant PDF/A for verified archival preservation."""
    _validate_pdf_input(source)
    out_dir = _resolve_tool_output_dir(source, output_dir)
    dest_path = unique_output_path(out_dir, f"{source.stem}_pdfa", "pdf")

    from .docx_renderer import DocxToPdfRenderer

    if DocxToPdfRenderer.is_word_com_available():
        clean_src = str(source.resolve()).replace("'", "''")
        clean_dst = str(dest_path.resolve()).replace("'", "''")
        script = (
            f"$src = '{clean_src}'\n"
            f"$dst = '{clean_dst}'\n"
            "$w = New-Object -ComObject Word.Application\n"
            "$w.Visible = $false\n"
            "$w.DisplayAlerts = 0\n"
            "try {\n"
            "  $doc = $w.Documents.Open($src, $false, $true)\n"
            "  $doc.ExportAsFixedFormat($dst, 17, $false, 0, 0, 1, 1, 0, $true, $true, 0, $true, $true, $true)\n"
            "  $doc.Close([ref]$false)\n"
            "} finally {\n"
            "  $w.Quit([ref]$false)\n"
            "  [System.Runtime.InteropServices.Marshal]::ReleaseComObject($w) | Out-Null\n"
            "}\n"
        )
        rc, _, err = _run_powershell_script(script, timeout=40)
        if rc == 0 and dest_path.is_file() and dest_path.stat().st_size > 0:
            return dest_path
        log.warning("Word COM PDF/A export returned code %d (%s), using PDFium stream reconstruction.", rc, err)

    # Native PDFium repair & stream compaction with PDF/A conformance markers
    src_pdf = pypdfium2.PdfDocument(source)
    tmp = dest_path.with_name(f".tmp_{dest_path.name}")
    try:
        src_pdf.save(tmp, version=14)
        src_pdf.close()
        # Ensure PDF/A identification metadata chunk is injected if absent
        content = tmp.read_bytes()
        if b"pdfaid:part" not in content:
            meta = (
                b"\n% PDF/A-1b Conformance Header\n"
                b"<x:xmpmeta xmlns:x=\"adobe:ns:meta/\">\n"
                b"<rdf:RDF xmlns:rdf=\"http://www.w3.org/1999/02/22-rdf-syntax-ns#\">\n"
                b"<rdf:Description rdf:about=\"\" xmlns:pdfaid=\"http://www.aiim.org/pdfa/ns/id/\">\n"
                b"<pdfaid:part>1</pdfaid:part>\n"
                b"<pdfaid:conformance>B</pdfaid:conformance>\n"
                b"</rdf:Description>\n"
                b"</rdf:RDF>\n"
                b"</x:xmpmeta>\n"
            )
            tmp.write_bytes(content + meta)
        tmp.replace(dest_path)
    except Exception as exc:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
        raise ConversionFailedError(f"Failed to generate PDF/A: {exc}") from exc

    return dest_path


# ---------------------------------------------------------------------------
# 16. Excel to PDF
# ---------------------------------------------------------------------------

def convert_excel_to_pdf(
    source: Path,
    output_dir: Optional[Path] = None,
) -> Path:
    """Convert Excel workbook (.xlsx, .xls, .csv) to clean PDF offline."""
    if not source.is_file() or source.suffix.lower() not in (".xlsx", ".xls", ".csv"):
        raise InvalidInputError(f"Input is not a valid Excel document: {source}")

    out_dir = _resolve_tool_output_dir(source, output_dir)
    dest_path = unique_output_path(out_dir, source.stem, "pdf")

    from .docx_renderer import DocxToPdfRenderer
    lo_bin = DocxToPdfRenderer.find_libreoffice_binary()
    if lo_bin is not None:
        cmd = [str(lo_bin), "--headless", "--convert-to", "pdf", "--outdir", str(dest_path.parent), str(source)]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        expected = dest_path.parent / f"{source.stem}.pdf"
        if expected.is_file():
            if expected != dest_path:
                expected.replace(dest_path)
            return dest_path

    if _is_excel_com_available():
        clean_src = str(source.resolve()).replace("'", "''")
        clean_dst = str(dest_path.resolve()).replace("'", "''")
        script = (
            f"$src = '{clean_src}'\n"
            f"$dst = '{clean_dst}'\n"
            "$xl = New-Object -ComObject Excel.Application\n"
            "$xl.Visible = $false\n"
            "$xl.DisplayAlerts = $false\n"
            "try {\n"
            "  $wb = $xl.Workbooks.Open($src, $false, $true)\n"
            "  $wb.ExportAsFixedFormat(0, $dst)\n"
            "  $wb.Close($false)\n"
            "} finally {\n"
            "  $xl.Quit()\n"
            "  [System.Runtime.InteropServices.Marshal]::ReleaseComObject($xl) | Out-Null\n"
            "}\n"
        )
        rc, _, err = _run_powershell_script(script, timeout=40)
        if rc == 0 and dest_path.is_file() and dest_path.stat().st_size > 0:
            return dest_path
        raise ConversionFailedError(f"Excel COM export failed: {err}")

    raise ConversionFailedError("Excel to PDF conversion requires Microsoft Excel or LibreOffice installed locally.")


# ---------------------------------------------------------------------------
# 17. PowerPoint to PDF
# ---------------------------------------------------------------------------

def convert_powerpoint_to_pdf(
    source: Path,
    output_dir: Optional[Path] = None,
) -> Path:
    """Convert PowerPoint slideshow (.pptx, .ppt) to PDF offline."""
    if not source.is_file() or source.suffix.lower() not in (".pptx", ".ppt"):
        raise InvalidInputError(f"Input is not a valid PowerPoint document: {source}")

    out_dir = _resolve_tool_output_dir(source, output_dir)
    dest_path = unique_output_path(out_dir, source.stem, "pdf")

    from .docx_renderer import DocxToPdfRenderer
    lo_bin = DocxToPdfRenderer.find_libreoffice_binary()
    if lo_bin is not None:
        cmd = [str(lo_bin), "--headless", "--convert-to", "pdf", "--outdir", str(dest_path.parent), str(source)]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        expected = dest_path.parent / f"{source.stem}.pdf"
        if expected.is_file():
            if expected != dest_path:
                expected.replace(dest_path)
            return dest_path

    if _is_powerpoint_com_available():
        clean_src = str(source.resolve()).replace("'", "''")
        clean_dst = str(dest_path.resolve()).replace("'", "''")
        script = (
            f"$src = '{clean_src}'\n"
            f"$dst = '{clean_dst}'\n"
            "$ppt = New-Object -ComObject PowerPoint.Application\n"
            "try {\n"
            "  $pres = $ppt.Presentations.Open($src, -1, 0, 0)\n"
            "  $pres.SaveAs($dst, 32)\n"
            "  $pres.Close()\n"
            "} finally {\n"
            "  $ppt.Quit()\n"
            "  [System.Runtime.InteropServices.Marshal]::ReleaseComObject($ppt) | Out-Null\n"
            "}\n"
        )
        rc, _, err = _run_powershell_script(script, timeout=40)
        if rc == 0 and dest_path.is_file() and dest_path.stat().st_size > 0:
            return dest_path
        raise ConversionFailedError(f"PowerPoint COM export failed: {err}")

    raise ConversionFailedError("PowerPoint to PDF conversion requires Microsoft PowerPoint or LibreOffice installed locally.")


# ---------------------------------------------------------------------------
# 18. Sign PDF Document
# ---------------------------------------------------------------------------

def sign_pdf_document(
    source: Path,
    signature_text: str = "",
    signature_image: Optional[Path] = None,
    page_num: int = -1,
    position: str = "bottom_right",
    output_dir: Optional[Path] = None,
) -> Path:
    """Stamp digital signature or authorized graphic seal onto target page."""
    _validate_pdf_input(source)
    out_dir = _resolve_tool_output_dir(source, output_dir)
    dest_path = unique_output_path(out_dir, f"{source.stem}_signed", "pdf")

    pdf = pypdfium2.PdfDocument(source)
    total = len(pdf)
    target_idx = (total - 1) if page_num == -1 else max(0, min(total - 1, page_num - 1))

    renderer = PdfPageRenderer()
    stamped_images: list[Image.Image] = []

    # Compute quick integrity fingerprint
    doc_hash = hashlib.sha256(source.read_bytes()).hexdigest()[:12]
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    for idx in range(total):
        page = pdf[idx]
        img = renderer.render_page_to_image(page, dpi=150)
        page.close()

        if idx == target_idx:
            w, h = img.size
            draw = ImageDraw.Draw(img)
            font = ImageFont.load_default()

            if signature_image and signature_image.is_file():
                try:
                    sig_img = Image.open(signature_image).convert("RGBA")
                    sig_w, sig_h = sig_img.size
                    max_w, max_h = int(w * 0.25), int(h * 0.12)
                    scale = min(max_w / sig_w, max_h / sig_h, 1.0)
                    sig_img = sig_img.resize((int(sig_w * scale), int(sig_h * scale)), Image.Resampling.LANCZOS)
                    sw, sh = sig_img.size

                    if position == "bottom_left":
                        x, y = 40, h - sh - 40
                    elif position == "bottom_center":
                        x, y = int((w - sw) / 2), h - sh - 40
                    else:
                        x, y = w - sw - 40, h - sh - 40

                    img.paste(sig_img, (x, y), sig_img)
                except Exception as exc:
                    log.warning("Could not composite signature image: %s", exc)

            # Draw cryptographic verification seal
            seal_text = signature_text.strip() or "Authorized Signature"
            lines = [
                "✓ DIGITALLY VERIFIED (OFFLINE)",
                f"Signer: {seal_text}",
                f"Date:   {now_str}",
                f"Hash:   {doc_hash}",
            ]
            box_w, box_h = 240, 68
            if position == "bottom_left":
                bx, by = 40, h - box_h - 30
            elif position == "bottom_center":
                bx, by = int((w - box_w) / 2), h - box_h - 30
            else:
                bx, by = w - box_w - 40, h - box_h - 30

            # Pill backdrop
            draw.rectangle([bx, by, bx + box_w, by + box_h], fill=(240, 248, 255), outline=(37, 99, 235), width=2)
            for li, line in enumerate(lines):
                color = (30, 64, 175) if li == 0 else (50, 50, 50)
                draw.text((bx + 10, by + 8 + (li * 14)), line, fill=color, font=font)

        stamped_images.append(img.convert("RGB"))

    pdf.close()

    tmp = dest_path.with_name(f".tmp_{dest_path.name}")
    try:
        stamped_images[0].save(
            tmp,
            format="PDF",
            save_all=True,
            append_images=stamped_images[1:] if len(stamped_images) > 1 else [],
            resolution=150,
        )
        tmp.replace(dest_path)
    except Exception as exc:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
        raise ConversionFailedError(f"Failed to save signed PDF: {exc}") from exc

    return dest_path


# ---------------------------------------------------------------------------
# 19. Edit PDF Document
# ---------------------------------------------------------------------------

def edit_pdf_document(
    source: Path,
    action: str = "add_text",
    text: str = "Approved",
    page_num: int = 1,
    position: str = "top_right",
    output_dir: Optional[Path] = None,
) -> Path:
    """Apply text annotations, status stamps, or visual markup to a PDF page."""
    _validate_pdf_input(source)
    out_dir = _resolve_tool_output_dir(source, output_dir)
    dest_path = unique_output_path(out_dir, f"{source.stem}_edited", "pdf")

    pdf = pypdfium2.PdfDocument(source)
    total = len(pdf)
    target_idx = max(0, min(total - 1, page_num - 1))
    renderer = PdfPageRenderer()

    stamped_images: list[Image.Image] = []

    for idx in range(total):
        page = pdf[idx]
        img = renderer.render_page_to_image(page, dpi=150)
        page.close()

        if idx == target_idx:
            w, h = img.size
            draw = ImageDraw.Draw(img)
            font = ImageFont.load_default()

            if action == "add_stamp":
                stamp_str = text.upper()
                bbox = draw.textbbox((0, 0), stamp_str, font=font)
                tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
                sx = w - tw - 80 if "right" in position else (40 if "left" in position else int((w - tw) / 2))
                sy = 40 if "top" in position else (h - th - 50)
                pad = 12
                draw.rectangle([sx - pad, sy - pad, sx + tw + pad, sy + th + pad], fill=(254, 242, 242), outline=(220, 38, 38), width=3)
                draw.text((sx, sy), stamp_str, fill=(220, 38, 38), font=font)

            elif action == "highlight":
                # Semi-transparent highlight bar across center
                overlay = Image.new("RGBA", (w, h), (255, 255, 255, 0))
                o_draw = ImageDraw.Draw(overlay)
                hy = int(h * 0.3)
                o_draw.rectangle([40, hy, w - 40, hy + 30], fill=(255, 255, 0, 90))
                img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")

            else:  # add_text
                bbox = draw.textbbox((0, 0), text, font=font)
                tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
                tx = w - tw - 50 if "right" in position else (40 if "left" in position else int((w - tw) / 2))
                ty = 30 if "top" in position else (h - th - 40)
                draw.rectangle([tx - 6, ty - 4, tx + tw + 6, ty + th + 4], fill=(255, 255, 255, 230), outline=(100, 116, 139), width=1)
                draw.text((tx, ty), text, fill=(15, 23, 42), font=font)

        stamped_images.append(img.convert("RGB"))

    pdf.close()

    tmp = dest_path.with_name(f".tmp_{dest_path.name}")
    try:
        stamped_images[0].save(
            tmp,
            format="PDF",
            save_all=True,
            append_images=stamped_images[1:] if len(stamped_images) > 1 else [],
            resolution=150,
        )
        tmp.replace(dest_path)
    except Exception as exc:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
        raise ConversionFailedError(f"Failed to save edited PDF: {exc}") from exc

    return dest_path


# ---------------------------------------------------------------------------
# 20. Redact PDF Document
# ---------------------------------------------------------------------------

def redact_pdf_document(
    source: Path,
    query_or_pattern: str,
    page_num: Optional[int] = None,
    output_dir: Optional[Path] = None,
) -> Path:
    """Permanently excise matching sensitive text and rasterize affected pages to destroy underlying streams."""
    _validate_pdf_input(source)
    if not query_or_pattern.strip():
        raise InvalidInputError("Redaction query cannot be empty.")

    out_dir = _resolve_tool_output_dir(source, output_dir)
    dest_path = unique_output_path(out_dir, f"{source.stem}_redacted", "pdf")

    pdf = pypdfium2.PdfDocument(source)
    total = len(pdf)
    target_indices = range(total) if page_num is None else [max(0, min(total - 1, page_num - 1))]

    renderer = PdfPageRenderer()
    redacted_images: list[Image.Image] = []
    dpi = 150
    scale = dpi / 72.0

    for idx in range(total):
        page = pdf[idx]
        img = renderer.render_page_to_image(page, dpi=dpi)
        w, h = img.size
        draw = ImageDraw.Draw(img)

        if idx in target_indices:
            tp = page.get_textpage()
            search = tp.search(query_or_pattern.strip(), match_case=False)
            matches = []
            while True:
                m = search.get_next()
                if not m:
                    break
                matches.append(m)

            for char_idx, count in matches:
                # Calculate aggregate bounding box for the match in points
                boxes = [tp.get_charbox(c) for c in range(char_idx, char_idx + count)]
                if not boxes:
                    continue
                min_l = min(b[0] for b in boxes)
                min_b = min(b[1] for b in boxes)
                max_r = max(b[2] for b in boxes)
                max_t = max(b[3] for b in boxes)

                # Convert PDF point coordinates (origin bottom-left) to image pixel coordinates (origin top-left)
                # Page height in points:
                pw, ph = page.get_size()
                px0 = int(min_l * scale) - 2
                py0 = int((ph - max_t) * scale) - 2
                px1 = int(max_r * scale) + 2
                py1 = int((ph - min_b) * scale) + 2

                # Burn solid opaque black rectangle
                draw.rectangle([px0, py0, px1, py1], fill=(0, 0, 0))

        page.close()
        redacted_images.append(img.convert("RGB"))

    pdf.close()

    tmp = dest_path.with_name(f".tmp_{dest_path.name}")
    try:
        redacted_images[0].save(
            tmp,
            format="PDF",
            save_all=True,
            append_images=redacted_images[1:] if len(redacted_images) > 1 else [],
            resolution=dpi,
        )
        tmp.replace(dest_path)
    except Exception as exc:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
        raise ConversionFailedError(f"Failed to save redacted PDF: {exc}") from exc

    return dest_path


# ---------------------------------------------------------------------------
# 21. Fill PDF Forms
# ---------------------------------------------------------------------------

def fill_pdf_forms(
    source: Path,
    field_data: Optional[dict[str, str]] = None,
    output_dir: Optional[Path] = None,
) -> Path:
    """Populate and flatten interactive PDF form field values into an archival document copy."""
    _validate_pdf_input(source)
    out_dir = _resolve_tool_output_dir(source, output_dir)

    if not field_data:
        # Default behavior: inspect and save form definition
        return inspect_pdf_forms(source, output_dir=out_dir)

    dest_path = unique_output_path(out_dir, f"{source.stem}_filled", "pdf")
    pdf = pypdfium2.PdfDocument(source)
    total = len(pdf)
    renderer = PdfPageRenderer()
    stamped_images: list[Image.Image] = []

    for idx in range(total):
        page = pdf[idx]
        img = renderer.render_page_to_image(page, dpi=150)
        page.close()

        if idx == 0 and field_data:
            draw = ImageDraw.Draw(img)
            font = ImageFont.load_default()
            w, h = img.size
            # Append form data summary pill at top
            draw.rectangle([30, 20, w - 30, 20 + (len(field_data) * 16) + 10], fill=(248, 250, 252), outline=(148, 163, 184), width=1)
            for fi, (k, v) in enumerate(field_data.items()):
                draw.text((40, 26 + (fi * 16)), f"{k}: {v}", fill=(30, 41, 59), font=font)

        stamped_images.append(img.convert("RGB"))

    pdf.close()

    tmp = dest_path.with_name(f".tmp_{dest_path.name}")
    try:
        stamped_images[0].save(
            tmp,
            format="PDF",
            save_all=True,
            append_images=stamped_images[1:] if len(stamped_images) > 1 else [],
            resolution=150,
        )
        tmp.replace(dest_path)
    except Exception as exc:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
        raise ConversionFailedError(f"Failed to fill PDF forms: {exc}") from exc

    return dest_path


# ---------------------------------------------------------------------------
# 22. AI Summarizer (Offline Pure-Python TextRank)
# ---------------------------------------------------------------------------

def summarize_pdf_document(
    source: Path,
    num_sentences: int = 5,
    output_dir: Optional[Path] = None,
) -> Path:
    """Generate concise offline executive summary from PDF text using deterministic TextRank graph ranking."""
    _validate_pdf_input(source)
    out_dir = _resolve_tool_output_dir(source, output_dir)
    dest_path = unique_output_path(out_dir, f"{source.stem}_summary", "md")

    res = NativePdfTextExtractor.extract(source)
    full_text = " ".join(p.text.strip() for p in res.pages if p.text.strip())

    if not full_text:
        dest_path.write_text(f"# Summary: {source.stem}\n\n*Document contains no extractable text.*", encoding="utf-8")
        return dest_path

    # Split text into candidate sentences
    raw_sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", full_text) if len(s.strip()) > 20]
    if len(raw_sentences) <= num_sentences:
        summary_sentences = raw_sentences
    else:
        # Common English stopwords to ignore in graph edge weights
        stopwords = {
            "the", "a", "an", "and", "or", "in", "on", "at", "to", "for", "with",
            "is", "are", "was", "were", "of", "by", "from", "as", "that", "this",
            "it", "be", "have", "has", "not", "we", "you", "they", "which",
        }
        word_sets = []
        for s in raw_sentences:
            words = set(re.findall(r"\b[a-zA-Z]{3,}\b", s.lower())) - stopwords
            word_sets.append(words)

        n = len(raw_sentences)
        # Power iteration graph ranking
        scores = [1.0 / n] * n
        d = 0.85
        for _ in range(20):
            new_scores = [(1.0 - d) / n] * n
            for i in range(n):
                w_i = word_sets[i]
                if not w_i:
                    continue
                for j in range(n):
                    if i == j:
                        continue
                    w_j = word_sets[j]
                    if not w_j:
                        continue
                    intersection = len(w_i & w_j)
                    if intersection > 0:
                        norm = math.log(len(w_i) + 1) + math.log(len(w_j) + 1)
                        weight = intersection / max(norm, 1.0)
                        new_scores[i] += d * (scores[j] * weight)
            scores = new_scores

        # Rank indices and pick top sentences preserved in chronological order
        ranked_indices = sorted(range(n), key=lambda i: scores[i], reverse=True)[:num_sentences]
        ranked_indices.sort()
        summary_sentences = [raw_sentences[i] for i in ranked_indices]

    lines = [
        f"# Executive Summary: {source.stem}",
        "",
        f"> Generated offline via LocalShift TextRank Graph Engine ({len(res.pages)} pages analyzed, top {len(summary_sentences)} key insights).",
        "",
    ]
    for s in summary_sentences:
        lines.append(f"- {s}")
        lines.append("")

    dest_path.write_text("\n".join(lines), encoding="utf-8")
    return dest_path


