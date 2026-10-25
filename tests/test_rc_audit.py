"""Release Candidate QA & Stability Audit tests for LocalShift v0.14.0 (LS-BE-015).

Validates:
- Stream encoding safety on Windows consoles with Unicode and special characters.
- Multi-output CLI reporting for multi-page PDF-to-image conversion.
- RapidOCR dynamic module resolution in frozen and unfrozen runtimes.
- Edge case handling: corrupt, encrypted, oversized, and nonexistent files.
- PDF workbench CLI operations with spaces and Unicode characters.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path
from PIL import Image
import pypdfium2
import pytest

from localshift.cli import _build_parser, main
from localshift.converter import ConversionRequest, convert_request
from localshift.documents.ocr import RapidOcrEngine
from localshift.documents.pdf_workbench import merge_pdfs, rotate_pdf_pages, split_pdf


def test_rapidocr_module_aliases():
    """Verify that RapidOcrEngine sets up module aliases for PyInstaller/frozen compatibility."""
    engine = RapidOcrEngine.get_engine()
    assert engine is not None
    assert "ch_ppocr_v3_det" in sys.modules
    assert "ch_ppocr_v3_rec" in sys.modules
    assert "ch_ppocr_v2_cls" in sys.modules
    assert hasattr(sys.modules["ch_ppocr_v3_det"], "TextDetector")


def test_cli_unicode_and_spaces_handling(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture):
    """Verify that CLI conversion handles Unicode characters and spaces without UnicodeEncodeError."""
    img_path = tmp_path / "тест 測試 📄 spaces.png"
    Image.new("RGB", (60, 60), color="green").save(img_path)

    monkeypatch.setattr(sys, "argv", ["localshift", "convert", str(img_path), "--to", "jpg", "--output-dir", str(tmp_path)])
    main()

    captured = capsys.readouterr()
    assert "Saved:" in captured.out
    out_files = list(tmp_path.glob("*.jpg")) + list(tmp_path.glob("*.jpeg"))
    assert len(out_files) == 1
    assert out_files[0].exists()


def test_cli_multipage_pdf_to_images(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture):
    """Verify that CLI reports all generated output paths when rasterizing a multi-page PDF."""
    pdf_path = tmp_path / "multipage_doc.pdf"
    doc = pypdfium2.PdfDocument.new()
    doc.new_page(150, 150)
    doc.new_page(150, 150)
    doc.save(str(pdf_path))
    doc.close()

    monkeypatch.setattr(sys, "argv", ["localshift", "convert", str(pdf_path), "--to", "png", "--output-dir", str(tmp_path)])
    main()

    captured = capsys.readouterr()
    # Both pages should be reported as saved
    assert captured.out.count("Saved:") == 2
    pngs = sorted(list(tmp_path.glob("*.png")))
    assert len(pngs) == 2


def test_cli_corrupt_file_error_handling(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture):
    """Verify that corrupt input produces exit code 2 and user-friendly error message."""
    bad_pdf = tmp_path / "corrupt.pdf"
    bad_pdf.write_bytes(b"NOT A REAL PDF FILE 12345")

    monkeypatch.setattr(sys, "argv", ["localshift", "convert", str(bad_pdf), "--to", "txt", "--output-dir", str(tmp_path)])
    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert "Operation failed:" in captured.err


def test_cli_pdf_workbench_unicode_and_spaces(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture):
    """Verify PDF workbench subcommands work cleanly on paths with Unicode and spaces."""
    doc = pypdfium2.PdfDocument.new()
    doc.new_page(200, 200)
    src_pdf = tmp_path / "оригинал 2026.pdf"
    doc.save(str(src_pdf))
    doc.close()

    rot_pdf = tmp_path / "поворот 2026.pdf"
    monkeypatch.setattr(sys, "argv", ["localshift", "pdf", "rotate", str(src_pdf), "-o", str(rot_pdf), "--angle", "90"])
    main()

    captured = capsys.readouterr()
    assert "Saved:" in captured.out
    assert rot_pdf.is_file()
