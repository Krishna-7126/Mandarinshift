"""
tests/test_document_foundation.py — Verification of document format foundation,
sniffing logic, and benchmark fixture integrity (LS-BE-006A).
"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from tests.benchmark_generator import generate_benchmark_fixtures


def sniff_document_container(path: Path) -> str | None:
    """Document container sniffer specification for future document engine.

    Guarantees:
    - Verifies %PDF- magic bytes for PDF.
    - Verifies ZIP signature + [Content_Types].xml + word/ directory parts for DOCX.
    - Explicitly rejects arbitrary ZIP files that lack OpenXML Word structure.
    """
    try:
        with open(path, "rb") as f:
            header = f.read(5)
            if header == b"%PDF-":
                return "pdf"
    except OSError:
        pass

    try:
        if zipfile.is_zipfile(path):
            with zipfile.ZipFile(path, "r") as zf:
                names = zf.namelist()
                if "[Content_Types].xml" in names and any(n.startswith("word/") for n in names):
                    return "docx"
    except Exception:
        pass

    return None


class TestDocumentSniffing:
    def test_sniffs_valid_pdf_fixtures(self, tmp_path: Path):
        fixtures = generate_benchmark_fixtures(tmp_path / "fixtures")
        for fix_id, path in fixtures.items():
            # doc_09_corrupt has %PDF-1.4 header as well
            assert sniff_document_container(path) == "pdf"

    def test_arbitrary_zip_is_not_detected_as_docx(self, tmp_path: Path):
        zip_file = tmp_path / "arbitrary.zip"
        with zipfile.ZipFile(zip_file, "w") as zf:
            zf.writestr("archive.txt", "just a text file")
            zf.writestr("data/table.csv", "1,2,3")

        assert sniff_document_container(zip_file) is None

    def test_valid_docx_container_detected(self, tmp_path: Path):
        docx_file = tmp_path / "sample.docx"
        with zipfile.ZipFile(docx_file, "w") as zf:
            zf.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types></Types>')
            zf.writestr("word/document.xml", '<?xml version="1.0"?><w:document></w:document>')
            zf.writestr("_rels/.rels", '<?xml version="1.0"?><Relationships></Relationships>')

        assert sniff_document_container(docx_file) == "docx"

    def test_zip_with_content_types_only_is_not_docx(self, tmp_path: Path):
        fake_docx = tmp_path / "fake.docx"
        with zipfile.ZipFile(fake_docx, "w") as zf:
            zf.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types></Types>')
            # Missing word/ directory components (e.g. could be xlsx or pptx)
            zf.writestr("xl/workbook.xml", '<workbook></workbook>')

        assert sniff_document_container(fake_docx) is None


class TestBenchmarkFixtures:
    def test_benchmark_generator_generates_all_fixtures(self, tmp_path: Path):
        fixtures = generate_benchmark_fixtures(tmp_path)
        assert len(fixtures) == 18
        expected_keys = {
            "doc_01_simple_digital",
            "doc_02_multipage_digital",
            "doc_03_multicolumn",
            "doc_04_table",
            "doc_05_english_scan",
            "doc_06_hindi_scan",
            "doc_07_mixed_pages",
            "doc_08_rotated_page",
            "doc_09_corrupt",
            "doc_10_encrypted",
            "doc_11_unicode_digital",
            "doc_12_hierarchy",
            "doc_13_empty",
            "doc_14_interleaved_multicolumn",
            "doc_15_borderless_table",
            "doc_16_image_caption",
            "doc_17_headers_footers",
            "doc_18_dense_document",
        }
        assert set(fixtures.keys()) == expected_keys
        for path in fixtures.values():
            assert path.exists()
            assert path.stat().st_size > 0
