"""
tests.docx_fixture_generator — Deterministic DOCX fixture generator for DOCX -> PDF testing.

Generates:
1. docx_01_simple.docx: Simple single-page document with heading and paragraphs.
2. docx_02_multipage.docx: Multipage document (3 pages) with headings and page breaks.
3. docx_03_tables.docx: Tables with headers, row borders, and numeric data.
4. docx_04_images.docx: Embedded image with caption and text.
5. docx_05_headers_footers.docx: Header, footer, and hyperlinks.
6. docx_06_unicode_margins_landscape.docx: Custom margins, landscape section, multilingual Unicode.
"""
from __future__ import annotations

import io
import json
from pathlib import Path
from PIL import Image, ImageDraw
import docx
from docx.enum.section import WD_ORIENT, WD_SECTION
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches, Pt, RGBColor


FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "docx_documents"


def create_sample_image() -> bytes:
    """Generate a small 200x120 test PNG image in memory."""
    img = Image.new("RGB", (200, 120), color=(50, 120, 200))
    d = ImageDraw.Draw(img)
    d.rectangle([10, 10, 190, 110], outline=(255, 255, 255), width=3)
    d.text((40, 50), "LocalShift DOCX", fill=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def generate_all_fixtures() -> dict[str, dict]:
    """Generate all test DOCX documents and return ground truth metadata."""
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    ground_truth = {}

    # 1. docx_01_simple.docx
    doc1 = docx.Document()
    doc1.add_heading("LocalShift Simple Document", level=0)
    p1 = doc1.add_paragraph("This is a simple single-page test document for DOCX to PDF rendering.")
    p1.runs[0].font.size = Pt(11)
    p2 = doc1.add_paragraph()
    r_bold = p2.add_run("Bold text statement. ")
    r_bold.bold = True
    r_italic = p2.add_run("Italic text explanation. ")
    r_italic.italic = True
    r_plain = p2.add_run("Standard text continuing the paragraph.")
    p1_path = FIXTURES_DIR / "docx_01_simple.docx"
    doc1.save(str(p1_path))
    ground_truth["docx_01_simple.docx"] = {
        "title": "LocalShift Simple Document",
        "expected_pages": 1,
        "keywords": ["LocalShift Simple Document", "Bold text statement", "Italic text explanation"],
    }

    # 2. docx_02_multipage.docx
    doc2 = docx.Document()
    doc2.add_heading("Multipage Document Analysis", level=0)
    doc2.add_paragraph("Page 1 introductory overview and architectural summary.")
    doc2.add_page_break()
    doc2.add_heading("Section Two: Implementation Details", level=1)
    doc2.add_paragraph("Page 2 deep technical breakdown of document converters.")
    doc2.add_page_break()
    doc2.add_heading("Section Three: Verification and Results", level=1)
    doc2.add_paragraph("Page 3 final concluding remarks and test statistics.")
    p2_path = FIXTURES_DIR / "docx_02_multipage.docx"
    doc2.save(str(p2_path))
    ground_truth["docx_02_multipage.docx"] = {
        "title": "Multipage Document Analysis",
        "expected_pages": 3,
        "keywords": ["Page 1 introductory overview", "Section Two", "Section Three"],
    }

    # 3. docx_03_tables.docx
    doc3 = docx.Document()
    doc3.add_heading("System Benchmark Metrics", level=0)
    doc3.add_paragraph("Table comparison of offline rendering engines:")
    tbl = doc3.add_table(rows=4, cols=4)
    tbl.style = "Table Grid"
    headers = ["Backend", "Licensing", "Latency (s)", "Memory (MB)"]
    for i, h in enumerate(headers):
        tbl.cell(0, i).text = h
    rows_data = [
        ["LibreOffice", "MPL-2.0", "1.24", "145"],
        ["Word COM", "Proprietary", "0.85", "82"],
        ["Pure Python", "MIT", "N/A", "N/A"],
    ]
    for r_idx, row_values in enumerate(rows_data, start=1):
        for c_idx, val in enumerate(row_values):
            tbl.cell(r_idx, c_idx).text = val
    p3_path = FIXTURES_DIR / "docx_03_tables.docx"
    doc3.save(str(p3_path))
    ground_truth["docx_03_tables.docx"] = {
        "title": "System Benchmark Metrics",
        "expected_pages": 1,
        "keywords": ["Backend", "LibreOffice", "Word COM", "MPL-2.0", "145"],
    }

    # 4. docx_04_images.docx
    doc4 = docx.Document()
    doc4.add_heading("Document with Embedded Media", level=0)
    doc4.add_paragraph("Here is an architectural diagram embedded directly into Word:")
    img_bytes = create_sample_image()
    img_stream = io.BytesIO(img_bytes)
    doc4.add_picture(img_stream, width=Inches(3.5))
    doc4.add_paragraph("Figure 1: Architectural diagram for LocalShift document subsystem.")
    p4_path = FIXTURES_DIR / "docx_04_images.docx"
    doc4.save(str(p4_path))
    ground_truth["docx_04_images.docx"] = {
        "title": "Document with Embedded Media",
        "expected_pages": 1,
        "keywords": ["Document with Embedded Media", "Figure 1"],
    }

    # 5. docx_05_headers_footers.docx
    doc5 = docx.Document()
    sec5 = doc5.sections[0]
    sec5.header.paragraphs[0].text = "LocalShift Confidential Header"
    sec5.footer.paragraphs[0].text = "Page Footer — Internal Evaluation Only"
    doc5.add_heading("Document with Headers and Footers", level=0)
    doc5.add_paragraph("This document contains running headers and footers across all pages.")
    doc5.add_paragraph("Reference URL: https://github.com/Krishna-7126/LocalShift")
    p5_path = FIXTURES_DIR / "docx_05_headers_footers.docx"
    doc5.save(str(p5_path))
    ground_truth["docx_05_headers_footers.docx"] = {
        "title": "Document with Headers and Footers",
        "expected_pages": 1,
        "keywords": ["Document with Headers and Footers", "github.com/Krishna-7126/LocalShift"],
    }

    # 6. docx_06_unicode_margins_landscape.docx
    doc6 = docx.Document()
    sec6 = doc6.sections[0]
    sec6.orientation = WD_ORIENT.LANDSCAPE
    sec6.page_width = Inches(11.0)
    sec6.page_height = Inches(8.5)
    sec6.top_margin = Inches(0.75)
    sec6.bottom_margin = Inches(0.75)
    sec6.left_margin = Inches(0.75)
    sec6.right_margin = Inches(0.75)

    doc6.add_heading("Multilingual & Custom Layout Specification", level=0)
    doc6.add_paragraph("English: Universal offline document conversion for Windows.")
    doc6.add_paragraph("Spanish: Conversión de documentos fuera de línea rápida y segura.")
    doc6.add_paragraph("German: Sichere und zuverlässige Offline-Dokumentenkonvertierung.")
    doc6.add_paragraph("Hindi: स्थानीय ऑफ़लाइन दस्तावेज़ रूपांतरण इंजन।")
    doc6.add_paragraph("Chinese: 本地离线文档转换引擎，保护用户隐私。")
    doc6.add_paragraph("Japanese: 安全なオフラインドキュメント変換エンジン。")
    doc6.add_paragraph("Symbols & Math: α + β = γ, Δx / Δt, ∑(x_i) ≥ 0, 🔒 Privacy First.")
    p6_path = FIXTURES_DIR / "docx_06_unicode_margins_landscape.docx"
    doc6.save(str(p6_path))
    ground_truth["docx_06_unicode_margins_landscape.docx"] = {
        "title": "Multilingual & Custom Layout Specification",
        "expected_pages": 1,
        "keywords": [
            "Universal offline document conversion",
            "Conversión de documentos",
            "lokale",
            "隐私",
            "Privacy First",
        ],
    }

    # Save ground truth metadata
    gt_file = FIXTURES_DIR / "ground_truth.json"
    gt_file.write_text(json.dumps(ground_truth, indent=2, ensure_ascii=False), encoding="utf-8")
    return ground_truth


if __name__ == "__main__":
    gt = generate_all_fixtures()
    print(f"Generated {len(gt)} fixtures in {FIXTURES_DIR}")
