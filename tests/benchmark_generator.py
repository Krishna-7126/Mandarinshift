"""
tests/benchmark_generator.py — Deterministic synthetic document fixture generator.

Generates reproducible, legally clean PDF test fixtures for:
- Born-digital native text
- Multi-page documents
- Multi-column layouts (sequential and interleaved stream order)
- Tabular structures
- Scanned raster text pages (English & Hindi)
- Mixed native/scanned pages
- Rotated pages
- Encrypted/password-protected PDFs
- Corrupt/damaged PDFs
- Born-digital multilingual Unicode text (diacritics, symbols, Latin accents)
- Heading & paragraph structural hierarchy
- Truly empty/blank pages

Requires only Pillow, pypdfium2, and Python standard library.
"""
from __future__ import annotations

import io
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
    """Generate a clean, minimal PDF 1.4 byte string without external binaries.

    Uses standard Helvetica with WinAnsiEncoding for accurate Latin-1 / Western
    diacritic text representation and exact byte offsets.
    """
    if corrupt_trailer:
        return b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n%%EOF_CORRUPTED"

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

    # Object 3: Standard Font (Helvetica with WinAnsiEncoding for accented glyphs)
    objects.append(b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica/Encoding/WinAnsiEncoding>>")

    for i, text in enumerate(pages_text):
        safe_text = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        lines = safe_text.split("\n")
        stream_cmds = [b"BT", b"/F1 12 Tf", b"50 750 Td", b"14 TL"]
        for line_idx, line in enumerate(lines):
            line_bytes = line.encode("cp1252", errors="replace")
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


#: Ground truth text for all benchmark fixtures where expected text exists.
GROUND_TRUTH_TEXT: dict[str, str] = {
    "doc_01_simple_digital": (
        "LocalShift Document Engine\n"
        "This is a clean, single-page born-digital PDF document.\n"
        "It contains standard ASCII text suitable for evaluating native extraction."
    ),
    "doc_02_multipage_digital": (
        "Page 1 of 3\nSection 1: Evaluation of multi-page flow and sequential reading order.\n\n"
        "Page 2 of 3\nSection 2: Evaluation of multi-page flow and sequential reading order.\n\n"
        "Page 3 of 3\nSection 3: Evaluation of multi-page flow and sequential reading order."
    ),
    "doc_03_multicolumn": (
        "Column 1 Headline\nLocalShift provides local\nconversion workflows.\nPrivacy first.\n\n"
        "Column 2 Headline\nIndependent modular\nadapter architecture.\nZero network leakage."
    ),
    "doc_04_table": (
        "Item ID    Description       Qty    Unit Price    Total\n"
        "-------------------------------------------------------\n"
        "LS-001     Image Converter   1      $0.00         $0.00\n"
        "LS-002     Job Queue         1      $0.00         $0.00\n"
        "LS-003     Document Engine   1      $0.00         $0.00"
    ),
    "doc_05_english_scan": "",  # Raster image; 0 native text
    "doc_06_hindi_scan": "",    # Raster image; 0 native text
    "doc_07_mixed_pages": "Page 1: Digital Summary Report\nLocalShift engine supports mixed-content documents.",
    "doc_08_rotated_page": "Landscape orientation test.\nThis page has /Rotate 90 metadata.",
    "doc_09_corrupt": "",
    "doc_10_encrypted": "",
    "doc_11_unicode_digital": (
        "LocalShift Multilingual Unicode Test\n"
        "French: Café, naïve, résumé, façade.\n"
        "German: Übergröße, Äpfel, Füße, Straßenbahn.\n"
        "Spanish: Año del niño, pingüino, señorita.\n"
        "Symbols: 100% — OK, ±5mm, ©2026 LocalShift, £50 / €75."
    ),
    "doc_12_hierarchy": (
        "LOCALSHIFT ARCHITECTURE MANUAL\n\n"
        "1. Executive Overview\n"
        "LocalShift provides local, private conversion workflows.\n\n"
        "1.1 Design Principles\n"
        "- Privacy First: Zero network calls.\n"
        "- Safety Boundary: In-process path reservations and atomic file replacement.\n"
        "- Modularity: Directional adapter capability registry."
    ),
    "doc_13_empty": "",
    "doc_14_interleaved_multicolumn": (
        "Col 1 Line 1\nCol 1 Line 2\n\nCol 2 Line 1\nCol 2 Line 2"
    ),
}


def generate_benchmark_fixtures(target_dir: Path) -> dict[str, Path]:
    """Generate all 14 deterministic benchmark PDF fixtures in target_dir.

    Returns a mapping of stable fixture ID to output Path.
    """
    import pypdfium2

    target_dir.mkdir(parents=True, exist_ok=True)
    fixtures: dict[str, Path] = {}

    # 1. Simple digital text PDF
    p1 = target_dir / "doc_01_simple_digital.pdf"
    p1.write_bytes(_build_simple_pdf_bytes([GROUND_TRUTH_TEXT["doc_01_simple_digital"]]))
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

    # 3. Multi-column PDF (sequential stream order)
    p3 = target_dir / "doc_03_multicolumn.pdf"
    p3.write_bytes(_build_simple_pdf_bytes([GROUND_TRUTH_TEXT["doc_03_multicolumn"]]))
    fixtures["doc_03_multicolumn"] = p3

    # 4. Table PDF
    p4 = target_dir / "doc_04_table.pdf"
    p4.write_bytes(_build_simple_pdf_bytes([GROUND_TRUTH_TEXT["doc_04_table"]]))
    fixtures["doc_04_table"] = p4

    # 5. English scanned PDF (pure raster image via Pillow)
    p5 = target_dir / "doc_05_english_scan.pdf"
    img_en = Image.new("RGB", (600, 800), "white")
    draw_en = ImageDraw.Draw(img_en)
    draw_en.text((50, 50), "SCANNED INVOICE (ENGLISH)", fill="black")
    draw_en.text((50, 90), "Invoice Number: INV-2026-001", fill="black")
    draw_en.text((50, 120), "Customer: Tangerine Workflow Alternative", fill="black")
    draw_en.text((50, 150), "Amount Due: $0.00 (Open Source)", fill="black")
    img_en.save(p5, format="PDF")
    fixtures["doc_05_english_scan"] = p5

    # 6. Hindi scanned PDF (raster image with Devanagari text rendered to pixels)
    p6 = target_dir / "doc_06_hindi_scan.pdf"
    img_hi = Image.new("RGB", (600, 800), "white")
    draw_hi = ImageDraw.Draw(img_hi)
    draw_hi.text((50, 50), "LocalShift Hindi Document Scan", fill="black")
    draw_hi.text((50, 90), "नमस्ते दुनिया (Hello World in Hindi)", fill="black")
    draw_hi.text((50, 130), "यह एक हिंदी दस्तावेज़ परीक्षण है।", fill="black")
    img_hi.save(p6, format="PDF")
    fixtures["doc_06_hindi_scan"] = p6

    # 7. Genuine mixed pages: Page 1 digital native text, Page 2 scanned image
    p7 = target_dir / "doc_07_mixed_pages.pdf"
    p7_text_bytes = _build_simple_pdf_bytes([GROUND_TRUTH_TEXT["doc_07_mixed_pages"]])
    doc_p7_text = pypdfium2.PdfDocument(p7_text_bytes)
    doc_p7_scan = pypdfium2.PdfDocument(p5)
    doc_p7_merged = pypdfium2.PdfDocument.new()
    doc_p7_merged.import_pages(doc_p7_text, [0])
    doc_p7_merged.import_pages(doc_p7_scan, [0])
    doc_p7_merged.save(p7)
    doc_p7_text.close()
    doc_p7_scan.close()
    doc_p7_merged.close()
    fixtures["doc_07_mixed_pages"] = p7

    # 8. Rotated page PDF (90 degrees clockwise)
    p8 = target_dir / "doc_08_rotated_page.pdf"
    p8.write_bytes(
        _build_simple_pdf_bytes([GROUND_TRUTH_TEXT["doc_08_rotated_page"]], rotation=90)
    )
    fixtures["doc_08_rotated_page"] = p8

    # 9. Corrupt/damaged PDF (truncated trailer)
    p9 = target_dir / "doc_09_corrupt.pdf"
    p9.write_bytes(_build_simple_pdf_bytes(["Test"], corrupt_trailer=True))
    fixtures["doc_09_corrupt"] = p9

    # 10. Encrypted PDF marker/simulation
    p10 = target_dir / "doc_10_encrypted.pdf"
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

    # 11. Unicode digital text PDF (diacritics, accented letters, currency symbols)
    p11 = target_dir / "doc_11_unicode_digital.pdf"
    p11.write_bytes(_build_simple_pdf_bytes([GROUND_TRUTH_TEXT["doc_11_unicode_digital"]]))
    fixtures["doc_11_unicode_digital"] = p11

    # 12. Heading and paragraph structural hierarchy
    p12 = target_dir / "doc_12_hierarchy.pdf"
    p12.write_bytes(_build_simple_pdf_bytes([GROUND_TRUTH_TEXT["doc_12_hierarchy"]]))
    fixtures["doc_12_hierarchy"] = p12

    # 13. Truly empty / blank page PDF (0 text, 0 image objects)
    p13 = target_dir / "doc_13_empty.pdf"
    doc_empty = pypdfium2.PdfDocument.new()
    doc_empty.new_page(612, 792)
    doc_empty.save(p13)
    doc_empty.close()
    fixtures["doc_13_empty"] = p13

    # 14. Multi-column PDF with interleaved stream (to evaluate reading-order failure modes)
    p14 = target_dir / "doc_14_interleaved_multicolumn.pdf"
    stream_cmds = [
        b"BT", b"/F1 12 Tf",
        b"1 0 0 1 50 700 Tm", b"(Col 1 Line 1) Tj",
        b"1 0 0 1 300 700 Tm", b"(Col 2 Line 1) Tj",
        b"1 0 0 1 50 680 Tm", b"(Col 1 Line 2) Tj",
        b"1 0 0 1 300 680 Tm", b"(Col 2 Line 2) Tj",
        b"ET",
    ]
    stream_bytes = b"\n".join(stream_cmds)
    p14_pdf = (
        b"%PDF-1.4\n"
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Resources<</Font<</F1 4 0 R>>>>/Contents 5 0 R>>endobj\n"
        b"4 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica/Encoding/WinAnsiEncoding>>endobj\n"
        b"5 0 obj<</Length " + str(len(stream_bytes)).encode("ascii") + b">>\nstream\n"
        + stream_bytes + b"\nendstream\nendobj\n"
        b"xref\n0 6\n0000000000 65535 f \n"
        b"0000000009 00000 n \n0000000052 00000 n \n0000000105 00000 n \n0000000219 00000 n \n0000000300 00000 n \n"
        b"trailer\n<</Size 6/Root 1 0 R>>\nstartxref\n500\n%%EOF\n"
    )
    p14.write_bytes(p14_pdf)
    fixtures["doc_14_interleaved_multicolumn"] = p14

    return fixtures


if __name__ == "__main__":
    out = Path(__file__).parent / "fixtures" / "documents"
    generate_benchmark_fixtures(out)
    print(f"Generated {len(list(out.glob('*.pdf')))} fixtures in {out}")
