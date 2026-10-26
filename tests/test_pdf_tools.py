"""
tests/test_pdf_tools.py — Unit and integration tests for the PDF Productivity Suite & Engine.
"""
from __future__ import annotations

import json
from pathlib import Path
import pytest
import pypdfium2

from localshift.documents.pdf_tool_registry import (
    ALL_PDF_TOOLS,
    PdfToolRegistry,
    ToolAvailability,
    ToolCategory,
)
from localshift.documents.pdf_tools_engine import (
    add_page_numbers_to_pdf,
    add_watermark_to_pdf,
    compare_two_pdfs,
    compress_pdf_file,
    convert_excel_to_pdf,
    convert_html_to_pdf,
    convert_pdf_to_excel,
    convert_pdf_to_pdfa,
    convert_pdf_to_powerpoint,
    convert_powerpoint_to_pdf,
    crop_pdf_pages,
    delete_pdf_pages,
    edit_pdf_document,
    fill_pdf_forms,
    inspect_pdf_forms,
    ocr_pdf_document,
    pdf_to_markdown_file,
    redact_pdf_document,
    repair_pdf_file,
    sign_pdf_document,
    summarize_pdf_document,
    unlock_pdf_file,
)
from localshift.exceptions import InvalidInputError


@pytest.fixture
def sample_3page_pdf(tmp_path: Path) -> Path:
    """Create a clean 3-page test PDF document."""
    pdf = pypdfium2.PdfDocument.new()
    for i in range(3):
        pdf.new_page(200, 300)
    out = tmp_path / "sample_3page.pdf"
    pdf.save(out)
    pdf.close()
    return out


@pytest.fixture
def sample_text_pdf(tmp_path: Path) -> Path:
    """Create a PDF with text content for markdown export."""
    fixtures = Path(__file__).parent / "fixtures" / "documents" / "doc_01_simple_digital.pdf"
    if fixtures.is_file():
        return fixtures
    # Fallback minimal PDF
    pdf = pypdfium2.PdfDocument.new()
    pdf.new_page(300, 400)
    out = tmp_path / "text.pdf"
    pdf.save(out)
    pdf.close()
    return out


# ---------------------------------------------------------------------------
# 1. Registry Tests
# ---------------------------------------------------------------------------

class TestPdfToolRegistry:
    def test_all_tools_count(self):
        tools = PdfToolRegistry.get_all_tools()
        assert len(tools) >= 30
        assert len(ALL_PDF_TOOLS) >= 30

    def test_categories_populated(self):
        for cat in ToolCategory:
            cat_tools = PdfToolRegistry.get_tools_by_category(cat)
            assert len(cat_tools) > 0

    def test_search_functionality(self):
        # Search "merge"
        res = PdfToolRegistry.search_tools("merge")
        assert any(t.id == "merge_pdf" for t in res)

        # Search "word"
        res_word = PdfToolRegistry.search_tools("word")
        assert any(t.id == "pdf_to_word" for t in res_word)

        # Search non-existent
        res_empty = PdfToolRegistry.search_tools("nonexistent_xyz")
        assert len(res_empty) == 0

    def test_tool_availability_truthful(self):
        # Tools marked READY / AVAILABLE must report is_available == True
        for tool in PdfToolRegistry.get_all_tools():
            if tool.availability in (ToolAvailability.AVAILABLE, ToolAvailability.READY):
                assert tool.is_available is True
            elif tool.availability == ToolAvailability.CONFIG_REQUIRED:
                assert tool.setup_guide is not None or tool.limitations is not None
            elif tool.availability == ToolAvailability.PLANNED:
                assert tool.is_available is False
                assert tool.limitations is not None


# ---------------------------------------------------------------------------
# 2. Essential PDF Tools Engine Tests
# ---------------------------------------------------------------------------

class TestPdfToolsEngine:
    def test_delete_pages(self, sample_3page_pdf: Path, tmp_path: Path):
        # Delete page 2 from 3-page PDF -> 2 pages remaining
        out = delete_pdf_pages(sample_3page_pdf, pages_to_delete=[2], output_dir=tmp_path)
        assert out.is_file()
        doc = pypdfium2.PdfDocument(out)
        assert len(doc) == 2
        doc.close()

    def test_delete_pages_rejects_all_pages(self, sample_3page_pdf: Path, tmp_path: Path):
        with pytest.raises(InvalidInputError):
            delete_pdf_pages(sample_3page_pdf, pages_to_delete=[1, 2, 3], output_dir=tmp_path)

    def test_crop_pdf_pages(self, sample_3page_pdf: Path, tmp_path: Path):
        out = crop_pdf_pages(sample_3page_pdf, margin_pt=20.0, output_dir=tmp_path)
        assert out.is_file()
        doc = pypdfium2.PdfDocument(out)
        assert len(doc) == 3
        # Check that cropbox was adjusted
        cb = doc[0].get_cropbox()
        doc.close()
        # Original was 0, 0, 200, 300; cropped should be (20, 20, 180, 280)
        assert cb == (20.0, 20.0, 180.0, 280.0)

    def test_compress_pdf_file(self, sample_3page_pdf: Path, tmp_path: Path):
        out = compress_pdf_file(sample_3page_pdf, compression_level="high", output_dir=tmp_path)
        assert out.is_file()
        doc = pypdfium2.PdfDocument(out)
        assert len(doc) == 3
        doc.close()

    def test_repair_pdf_file(self, sample_3page_pdf: Path, tmp_path: Path):
        out = repair_pdf_file(sample_3page_pdf, output_dir=tmp_path)
        assert out.is_file()
        doc = pypdfium2.PdfDocument(out)
        assert len(doc) == 3
        doc.close()

    def test_pdf_to_markdown_file(self, sample_text_pdf: Path, tmp_path: Path):
        out = pdf_to_markdown_file(sample_text_pdf, output_dir=tmp_path)
        assert out.is_file()
        assert out.suffix == ".md"
        content = out.read_text(encoding="utf-8")
        assert len(content) > 0

    def test_add_page_numbers(self, sample_3page_pdf: Path, tmp_path: Path):
        out = add_page_numbers_to_pdf(sample_3page_pdf, format_str="Pg {n}/{total}", output_dir=tmp_path)
        assert out.is_file()
        doc = pypdfium2.PdfDocument(out)
        assert len(doc) == 3
        doc.close()

    def test_add_watermark(self, sample_3page_pdf: Path, tmp_path: Path):
        out = add_watermark_to_pdf(sample_3page_pdf, text="TEST STAMP", opacity=0.3, angle=30, output_dir=tmp_path)
        assert out.is_file()
        doc = pypdfium2.PdfDocument(out)
        assert len(doc) == 3
        doc.close()

    def test_compare_two_pdfs(self, sample_3page_pdf: Path, tmp_path: Path):
        p2 = tmp_path / "copy.pdf"
        p2.write_bytes(sample_3page_pdf.read_bytes())
        out = compare_two_pdfs(sample_3page_pdf, p2, output_dir=tmp_path)
        assert out.is_file()
        assert out.suffix == ".md"
        text = out.read_text(encoding="utf-8")
        assert "Page count match: `Yes`" in text

    def test_inspect_pdf_forms(self, sample_3page_pdf: Path, tmp_path: Path):
        out = inspect_pdf_forms(sample_3page_pdf, output_dir=tmp_path)
        assert out.is_file()
        assert out.suffix == ".json"
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["page_count"] == 3
        assert len(data["fields"]) == 3

    def test_convert_html_to_pdf(self, tmp_path: Path):
        html_file = tmp_path / "document.html"
        html_file.write_text("<h1>Invoice #1042</h1><p>Offline conversion test.</p>", encoding="utf-8")
        out = convert_html_to_pdf(html_file, output_dir=tmp_path)
        assert out.is_file()
        assert out.suffix == ".pdf"
        assert out.stat().st_size > 0
        doc = pypdfium2.PdfDocument(out)
        assert len(doc) >= 1
        doc.close()

    def test_ocr_pdf_document(self, sample_text_pdf: Path, tmp_path: Path):
        out = ocr_pdf_document(sample_text_pdf, output_format="txt", output_dir=tmp_path)
        assert out.is_file()
        assert out.suffix == ".txt"
        assert out.stat().st_size > 0

    def test_convert_pdf_to_excel(self, sample_text_pdf: Path, tmp_path: Path):
        import zipfile
        out = convert_pdf_to_excel(sample_text_pdf, output_dir=tmp_path)
        assert out.is_file()
        assert out.suffix == ".xlsx"
        assert out.stat().st_size > 0
        with zipfile.ZipFile(out) as z:
            assert "xl/workbook.xml" in z.namelist()
            assert "xl/worksheets/sheet1.xml" in z.namelist()

    def test_convert_pdf_to_powerpoint(self, sample_3page_pdf: Path, tmp_path: Path):
        import zipfile
        out = convert_pdf_to_powerpoint(sample_3page_pdf, output_dir=tmp_path)
        assert out.is_file()
        assert out.suffix == ".pptx"
        assert out.stat().st_size > 0
        with zipfile.ZipFile(out) as z:
            assert "ppt/presentation.xml" in z.namelist()

    def test_convert_pdf_to_pdfa(self, sample_3page_pdf: Path, tmp_path: Path):
        out = convert_pdf_to_pdfa(sample_3page_pdf, output_dir=tmp_path)
        assert out.is_file()
        assert out.suffix == ".pdf"
        assert out.stat().st_size > 0
        doc = pypdfium2.PdfDocument(out)
        assert len(doc) == 3
        doc.close()

    def test_convert_excel_to_pdf(self, tmp_path: Path):
        # Create minimal test xlsx
        test_xlsx = tmp_path / "data.xlsx"
        from localshift.documents.pdf_tools_engine import convert_pdf_to_excel
        sample_pdf = Path(__file__).parent / "fixtures" / "documents" / "doc_01_simple_digital.pdf"
        if not sample_pdf.is_file():
            sample_pdf = tmp_path / "gen.pdf"
            pdf = pypdfium2.PdfDocument.new()
            pdf.new_page(200, 200)
            pdf.save(sample_pdf)
            pdf.close()
        xlsx_file = convert_pdf_to_excel(sample_pdf, output_dir=tmp_path)
        out = convert_excel_to_pdf(xlsx_file, output_dir=tmp_path)
        assert out.is_file()
        assert out.suffix == ".pdf"
        assert out.stat().st_size > 0

    def test_sign_pdf_document(self, sample_3page_pdf: Path, tmp_path: Path):
        out = sign_pdf_document(sample_3page_pdf, signature_text="Alice Engineer", position="bottom_right", output_dir=tmp_path)
        assert out.is_file()
        doc = pypdfium2.PdfDocument(out)
        assert len(doc) == 3
        doc.close()

    def test_edit_pdf_document(self, sample_3page_pdf: Path, tmp_path: Path):
        # Test text annotation and stamp
        out1 = edit_pdf_document(sample_3page_pdf, action="add_text", text="Review copy", output_dir=tmp_path)
        assert out1.is_file()
        doc1 = pypdfium2.PdfDocument(out1)
        assert len(doc1) == 3
        doc1.close()

        out2 = edit_pdf_document(sample_3page_pdf, action="add_stamp", text="APPROVED", output_dir=tmp_path)
        assert out2.is_file()
        doc2 = pypdfium2.PdfDocument(out2)
        assert len(doc2) == 3
        doc2.close()

    def test_redact_pdf_document(self, tmp_path: Path):
        # Create a PDF with known text to redact
        test_pdf = tmp_path / "redact_test.pdf"
        pdf = pypdfium2.PdfDocument.new()
        p = pdf.new_page(300, 300)
        pdf.save(test_pdf)
        pdf.close()

        out = redact_pdf_document(test_pdf, query_or_pattern="SECRET", output_dir=tmp_path)
        assert out.is_file()
        doc = pypdfium2.PdfDocument(out)
        assert len(doc) == 1
        doc.close()

    def test_fill_pdf_forms(self, sample_3page_pdf: Path, tmp_path: Path):
        data = {"CustomerName": "Acme Corp", "InvoiceTotal": "$1,250.00"}
        out = fill_pdf_forms(sample_3page_pdf, field_data=data, output_dir=tmp_path)
        assert out.is_file()
        assert out.suffix == ".pdf"
        doc = pypdfium2.PdfDocument(out)
        assert len(doc) == 3
        doc.close()

    def test_summarize_pdf_document(self, sample_text_pdf: Path, tmp_path: Path):
        out = summarize_pdf_document(sample_text_pdf, num_sentences=3, output_dir=tmp_path)
        assert out.is_file()
        assert out.suffix == ".md"
        content = out.read_text(encoding="utf-8")
        assert "# Executive Summary" in content


