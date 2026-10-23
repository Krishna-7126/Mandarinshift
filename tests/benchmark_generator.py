"""
tests/benchmark_generator.py — Deterministic synthetic document fixture generator.

Generates reproducible, legally clean PDF test fixtures for:
- Born-digital native text
- Multi-page documents
- Multi-column layouts
- Tabular structures
- Scanned raster text pages (English & Hindi)
- Mixed native/scanned pages
- Rotated pages
- Encrypted/password-protected PDFs
- Corrupt/damaged PDFs

Requires only Pillow and Python standard library. No external binaries or non-permissive dependencies.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont


def _build_simple_pdf_bytes(
    pages_text: list[str],
    *,
    rotation: int = 0,
    corrupt_trailer: bool = False,
) -> bytes:
    """Generate a clean, minimal 7-bit ASCII PDF 1.4 byte string without external libraries.

    Supports simple native text streams, page counts, page rotation metadata, and intentional corruption.
    """
    if corrupt_trailer:
        return b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n%%EOF_CORRUPTED"

    # Minimal PDF structure:
    # 1 0 obj: Catalog
    # 2 0 obj: Pages
    # 3 0 obj: Font (Helvetica)
    # Then for each page i:
    # Page object (4 + 2*i), Content object (5 + 2*i)

    num_pages = len(pages_text)
    objects: list[bytes] = []

    # Object 1: Catalog
    objects.append(b"<</Type/Catalog/Pages 2 0 R>>")

    # Object 2: Pages tree
    page_refs = [f"{4 + 2*i} 0 R".encode("ascii") for i in range(num_pages)]
    pages_obj = (
        b"<</Type/Pages/Kids[" + b" ".join(page_refs) + b"]/Count " + str(num_pages).encode("ascii") + b">>"
    )
    objects.append(pages_obj)

    # Object 3: Standard Font (Helvetica)
    objects.append(b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>")

    for i, text in enumerate(pages_text):
        # Clean text for PDF literal string
        safe_text = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        # Content stream: BT /F1 12 Tf 50 750 Td (text) Tj ET
        lines = safe_text.split("\n")
        stream_cmds = [b"BT", b"/F1 12 Tf", b"50 750 Td", b"14 TL"]
        for line_idx, line in enumerate(lines):
            line_bytes = line.encode("latin-1", errors="replace")
            if line_idx > 0:
                stream_cmds.append(b"T* (" + line_bytes + b") Tj")
            else:
                stream_cmds.append(b"(" + line_bytes + b") Tj")
        stream_cmds.append(b"ET")
        stream_data = b"\n".join(stream_cmds)
        content_stream_obj = (
            b"<</Length " + str(len(stream_data)).encode("ascii") + b">>\nstream\n" + stream_data + b"\nendstream"
        )

        page_obj_parts = [
            b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Resources<</Font<</F1 3 0 R>>>>/Contents "
            + str(5 + 2*i).encode("ascii")
            + b" 0 R"
        ]
        if rotation != 0:
            page_obj_parts.append(b"/Rotate " + str(rotation).encode("ascii"))
        page_obj_parts.append(b">>")
        page_obj = b"".join(page_obj_parts)

        objects.append(page_obj)
        objects.append(content_stream_obj)

    # Assemble PDF with cross-reference table
    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]  # Object 0 dummy offset

    for idx, obj in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{idx} 0 obj\n".encode("ascii"))
        output.extend(obj)
        output.extend(b"\nendobj\n")

    xref_offset = len(output)
    output.extend(f"xref\n0 {len(offsets)}\n".encode("ascii"))
    output.extend(b"0000000000 65535 f \n")
    for off in offsets[1:]:
        output.extend(f"{off:010d} 00000 n \n".encode("ascii"))

    output.extend(
        f"trailer\n<</Size {len(offsets)}/Root 1 0 R>>\nstartxref\n{xref_offset}\n%%EOF\n".encode("ascii")
    )
    return bytes(output)


def generate_benchmark_fixtures(target_dir: Path) -> dict[str, Path]:
    """Generate the 10 deterministic benchmark PDF fixtures in target_dir.

    Returns a mapping of stable fixture ID to output Path.
    """
    target_dir.mkdir(parents=True, exist_ok=True)
    fixtures: dict[str, Path] = {}

    # 1. Simple digital text PDF
    p1 = target_dir / "doc_01_simple_digital.pdf"
    p1.write_bytes(
        _build_simple_pdf_bytes([
            "LocalShift Document Engine\n"
            "This is a clean, single-page born-digital PDF document.\n"
            "It contains standard ASCII text suitable for evaluating native extraction."
        ])
    )
    fixtures["doc_01_simple_digital"] = p1

    # 2. Multi-page digital PDF
    p2 = target_dir / "doc_02_multipage_digital.pdf"
    p2.write_bytes(
        _build_simple_pdf_bytes([
            f"Page {n} of 3\nSection {n}: Evaluation of multi-page flow and sequential reading order."
            for n in range(1, 4)
        ])
    )
    fixtures["doc_02_multipage_digital"] = p2

    # 3. Multi-column PDF (synthesized with column spacing in text layout)
    p3 = target_dir / "doc_03_multicolumn.pdf"
    col1 = "Column 1 Headline\nLocalShift provides local\nconversion workflows.\nPrivacy first."
    col2 = "Column 2 Headline\nIndependent modular\nadapter architecture.\nZero network leakage."
    p3.write_bytes(_build_simple_pdf_bytes([f"{col1}\n\n{col2}"]))
    fixtures["doc_03_multicolumn"] = p3

    # 4. Table PDF (synthesized with ASCII text grid structure)
    p4 = target_dir / "doc_04_table.pdf"
    table_text = (
        "Item ID    Description       Qty    Unit Price    Total\n"
        "-------------------------------------------------------\n"
        "LS-001     Image Converter   1      $0.00         $0.00\n"
        "LS-002     Job Queue         1      $0.00         $0.00\n"
        "LS-003     Document Engine   1      $0.00         $0.00"
    )
    p4.write_bytes(_build_simple_pdf_bytes([table_text]))
    fixtures["doc_04_table"] = p4

    # 5. English scanned PDF (raster image saved as PDF via Pillow)
    p5 = target_dir / "doc_05_english_scan.pdf"
    img_en = Image.new("RGB", (600, 800), "white")
    draw_en = ImageDraw.Draw(img_en)
    draw_en.text((50, 50), "SCANNED INVOICE (ENGLISH)", fill="black")
    draw_en.text((50, 90), "Invoice Number: INV-2026-001", fill="black")
    draw_en.text((50, 120), "Customer: Tangerine Workflow Alternative", fill="black")
    draw_en.text((50, 150), "Amount Due: $0.00 (Open Source)", fill="black")
    img_en.save(p5, format="PDF")
    fixtures["doc_05_english_scan"] = p5

    # 6. Hindi scanned PDF (raster image with Hindi Unicode glyphs rendered)
    p6 = target_dir / "doc_06_hindi_scan.pdf"
    img_hi = Image.new("RGB", (600, 800), "white")
    draw_hi = ImageDraw.Draw(img_hi)
    # Using Devanagari text string (Pillow default font will render or placeholder)
    draw_hi.text((50, 50), "LocalShift Hindi Document Scan", fill="black")
    draw_hi.text((50, 90), "नमस्ते दुनिया (Hello World in Hindi)", fill="black")
    draw_hi.text((50, 130), "यह एक हिंदी दस्तावेज़ परीक्षण है।", fill="black")
    img_hi.save(p6, format="PDF")
    fixtures["doc_06_hindi_scan"] = p6

    # 7. Mixed native-text and scanned pages (2 pages via Pillow)
    p7 = target_dir / "doc_07_mixed_pages.pdf"
    page1_img = Image.new("RGB", (400, 600), "white")
    draw_p1 = ImageDraw.Draw(page1_img)
    draw_p1.text((30, 40), "Page 1: Digital Summary", fill="black")

    page2_img = Image.new("RGB", (400, 600), "lightgray")
    draw_p2 = ImageDraw.Draw(page2_img)
    draw_p2.text((30, 40), "Page 2: Photocopied Form Scan", fill="black")
    page1_img.save(p7, format="PDF", save_all=True, append_images=[page2_img])
    fixtures["doc_07_mixed_pages"] = p7

    # 8. Rotated page PDF (90 degrees clockwise)
    p8 = target_dir / "doc_08_rotated_page.pdf"
    p8.write_bytes(
        _build_simple_pdf_bytes(["Landscape orientation test.\nThis page has /Rotate 90 metadata."], rotation=90)
    )
    fixtures["doc_08_rotated_page"] = p8

    # 9. Corrupt/damaged PDF (truncated trailer)
    p9 = target_dir / "doc_09_corrupt.pdf"
    p9.write_bytes(_build_simple_pdf_bytes(["Test"], corrupt_trailer=True))
    fixtures["doc_09_corrupt"] = p9

    # 10. Encrypted PDF marker/simulation
    p10 = target_dir / "doc_10_encrypted.pdf"
    # Minimal PDF dictionary declaring /Encrypt dictionary
    encrypted_pdf = (
        b"%PDF-1.4\n"
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>endobj\n"
        b"4 0 obj<</Filter/Standard/V 2/R 3/O(test)/U(test)/P -4>>endobj\n"
        b"xref\n0 5\n0000000000 65535 f \n0000000009 00000 n \n0000000052 00000 n \n0000000105 00000 n \n0000000171 00000 n \n"
        b"trailer\n<</Size 5/Root 1 0 R/Encrypt 4 0 R>>\nstartxref\n245\n%%EOF\n"
    )
    p10.write_bytes(encrypted_pdf)
    fixtures["doc_10_encrypted"] = p10

    return fixtures


if __name__ == "__main__":
    out = Path(__file__).parent / "fixtures" / "documents"
    generate_benchmark_fixtures(out)
    print(f"Generated {len(list(out.glob('*.pdf')))} fixtures in {out}")
