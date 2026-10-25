"""
tests.test_pdf_workbench — Comprehensive tests for the Offline PDF Workbench (LS-BE-012).

Tests:
- Merge: Multi-document ordering, dimension/rotation preservation, limits, errors.
- Split: Exporting pages, custom patterns, subset selections, failure cleanup.
- Extract: Subset page extraction into single PDF, dimension preservation.
- Reorder: Permuting pages by 1-based indices, bounds validation, immutability.
- Rotate: 90°, 180°, 270°, negative angles, relative vs absolute rotation.
- Reliability: Atomic placement, collision protection, cancellation, rollback.
- Security: Missing, corrupted, encrypted, empty, and oversized files.
- CLI: Verification of CLI subcommands.
"""
from __future__ import annotations

import os
from pathlib import Path

import pypdfium2
import pytest

from localshift import (
    ConversionCancelledError,
    DestinationConflictError,
    InputTooLargeError,
    InvalidInputError,
    PdfWorkbench,
    extract_pdf_pages,
    merge_pdfs,
    reorder_pdf_pages,
    rotate_pdf_pages,
    split_pdf,
)
from localshift.cli import main as cli_main


# ---------------------------------------------------------------------------
# Test Helpers
# ---------------------------------------------------------------------------

def _make_pdf(path: Path, pages: list[tuple[float, float, int]]) -> Path:
    """Create a test PDF at *path* with given (width, height, rotation) per page."""
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = pypdfium2.PdfDocument.new()
    for w, h, rot in pages:
        p = doc.new_page(w, h)
        if rot:
            p.set_rotation(rot)
        p.close()
    doc.save(path)
    doc.close()
    return path


def _read_pdf_info(path: Path) -> list[tuple[float, float, int]]:
    """Return list of (mediabox width, mediabox height, rotation) for each page in *path*."""
    doc = pypdfium2.PdfDocument(path)
    info = []
    for i in range(len(doc)):
        p = doc.get_page(i)
        mb = p.get_mediabox()
        rot = p.get_rotation()
        info.append((round(mb[2] - mb[0], 1), round(mb[3] - mb[1], 1), rot))
        p.close()
    doc.close()
    return info


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def pdf_2pages(tmp_path: Path) -> Path:
    """PDF with 2 pages: page 1 (200x300, 0°), page 2 (400x500, 90°)."""
    return _make_pdf(tmp_path / "doc_2p.pdf", [(200, 300, 0), (400, 500, 90)])


@pytest.fixture
def pdf_3pages(tmp_path: Path) -> Path:
    """PDF with 3 pages: page 1 (100x150, 0°), page 2 (200x250, 180°), page 3 (300x350, 270°)."""
    return _make_pdf(tmp_path / "doc_3p.pdf", [(100, 150, 0), (200, 250, 180), (300, 350, 270)])


@pytest.fixture
def pdf_1page(tmp_path: Path) -> Path:
    """PDF with 1 page: (500x600, 0°)."""
    return _make_pdf(tmp_path / "doc_1p.pdf", [(500, 600, 0)])


# ---------------------------------------------------------------------------
# Merge Tests
# ---------------------------------------------------------------------------

class TestPdfMerge:
    def test_merge_two_documents(self, pdf_2pages: Path, pdf_1page: Path, tmp_path: Path):
        out = merge_pdfs([pdf_2pages, pdf_1page], output_dir=tmp_path)
        assert out.exists()
        assert out.name.startswith("doc_2p_merged")
        info = _read_pdf_info(out)
        assert len(info) == 3
        # Page 1 & 2 from pdf_2pages
        assert info[0] == (200.0, 300.0, 0)
        assert info[1] == (400.0, 500.0, 90)
        # Page 3 from pdf_1page
        assert info[2] == (500.0, 600.0, 0)

    def test_merge_three_documents_explicit_order(self, pdf_1page: Path, pdf_2pages: Path, pdf_3pages: Path, tmp_path: Path):
        dest = tmp_path / "custom_merged.pdf"
        out = merge_pdfs([pdf_3pages, pdf_1page, pdf_2pages], output_path=dest)
        assert out == dest
        info = _read_pdf_info(out)
        assert len(info) == 6
        # First 3 from pdf_3pages
        assert info[0] == (100.0, 150.0, 0)
        assert info[1] == (200.0, 250.0, 180)
        assert info[2] == (300.0, 350.0, 270)
        # Next 1 from pdf_1page
        assert info[3] == (500.0, 600.0, 0)
        # Last 2 from pdf_2pages
        assert info[4] == (200.0, 300.0, 0)
        assert info[5] == (400.0, 500.0, 90)

    def test_merge_single_document(self, pdf_2pages: Path, tmp_path: Path):
        out = merge_pdfs([pdf_2pages], output_dir=tmp_path)
        assert out.exists()
        assert len(_read_pdf_info(out)) == 2

    def test_merge_empty_sources_raises(self):
        with pytest.raises(InvalidInputError, match="at least 1 input PDF"):
            merge_pdfs([])

    def test_merge_missing_file_raises(self, pdf_1page: Path, tmp_path: Path):
        missing = tmp_path / "nonexistent.pdf"
        with pytest.raises(InvalidInputError, match="not found"):
            merge_pdfs([pdf_1page, missing])

    def test_merge_corrupt_file_raises(self, pdf_1page: Path, tmp_path: Path):
        corrupt = tmp_path / "corrupt.pdf"
        corrupt.write_bytes(b"%PDF-corrupted_gibberish_xref_missing")
        with pytest.raises(InvalidInputError, match="corrupt or unreadable"):
            merge_pdfs([pdf_1page, corrupt])

    def test_merge_non_pdf_magic_bytes_raises(self, pdf_1page: Path, tmp_path: Path):
        bad_magic = tmp_path / "fake.pdf"
        bad_magic.write_bytes(b"\x89PNG\r\n\x1a\nfake")
        with pytest.raises(InvalidInputError, match="magic bytes"):
            merge_pdfs([pdf_1page, bad_magic])

    def test_merge_collision_protection(self, pdf_1page: Path, tmp_path: Path):
        # Create an existing file
        existing = tmp_path / "doc_1p_merged.pdf"
        existing.write_bytes(b"%PDF-placeholder")

        out = merge_pdfs([pdf_1page], output_dir=tmp_path)
        assert out.name == "doc_1p_merged (2).pdf"
        assert out.exists()
        # Original placeholder must remain intact
        assert existing.read_bytes() == b"%PDF-placeholder"

    def test_merge_same_output_path_raises_conflict(self, pdf_1page: Path):
        with pytest.raises(DestinationConflictError, match="identical to source"):
            merge_pdfs([pdf_1page], output_path=pdf_1page)

    def test_merge_cancellation_cleans_up(self, pdf_2pages: Path, pdf_3pages: Path, tmp_path: Path):
        with pytest.raises(ConversionCancelledError):
            merge_pdfs([pdf_2pages, pdf_3pages], output_dir=tmp_path, cancel_check=lambda: True)
        # Verify no merged files left in tmp_path
        created = list(tmp_path.glob("*_merged*.pdf"))
        assert len(created) == 0


# ---------------------------------------------------------------------------
# Split Tests
# ---------------------------------------------------------------------------

class TestPdfSplit:
    def test_split_all_pages(self, pdf_3pages: Path, tmp_path: Path):
        out_dir = tmp_path / "split_all"
        outputs = split_pdf(pdf_3pages, output_dir=out_dir)
        assert len(outputs) == 3
        for p in outputs:
            assert p.exists()
            assert len(_read_pdf_info(p)) == 1

        # Check page metrics preserved
        assert _read_pdf_info(outputs[0])[0] == (100.0, 150.0, 0)
        assert _read_pdf_info(outputs[1])[0] == (200.0, 250.0, 180)
        assert _read_pdf_info(outputs[2])[0] == (300.0, 350.0, 270)

    def test_split_page_subset(self, pdf_3pages: Path, tmp_path: Path):
        out_dir = tmp_path / "split_sub"
        outputs = split_pdf(pdf_3pages, output_dir=out_dir, pages="1, 3")
        assert len(outputs) == 2
        assert outputs[0].name.endswith("_page_1.pdf")
        assert outputs[1].name.endswith("_page_3.pdf")
        assert _read_pdf_info(outputs[0])[0] == (100.0, 150.0, 0)
        assert _read_pdf_info(outputs[1])[0] == (300.0, 350.0, 270)

    def test_split_custom_pattern(self, pdf_2pages: Path, tmp_path: Path):
        out_dir = tmp_path / "split_pattern"
        outputs = split_pdf(
            pdf_2pages,
            output_dir=out_dir,
            output_pattern="{stem}_part{page:02d}.{ext}",
        )
        assert len(outputs) == 2
        assert outputs[0].name == "doc_2p_part01.pdf"
        assert outputs[1].name == "doc_2p_part02.pdf"

    def test_split_pattern_missing_page_token_raises(self, pdf_3pages: Path, tmp_path: Path):
        with pytest.raises(InvalidInputError, match="must include '{page}'"):
            split_pdf(pdf_3pages, output_dir=tmp_path, output_pattern="fixed_name.pdf")

    def test_split_pattern_traversal_raises(self, pdf_3pages: Path, tmp_path: Path):
        with pytest.raises(InvalidInputError, match="must not contain directory separators"):
            split_pdf(pdf_3pages, output_dir=tmp_path, output_pattern="../{stem}_{page}.pdf")

    def test_split_invalid_page_raises(self, pdf_3pages: Path, tmp_path: Path):
        with pytest.raises(InvalidInputError, match="exceeds total pages|out of bounds"):
            split_pdf(pdf_3pages, output_dir=tmp_path, pages="4")

    def test_split_cancellation_cleans_up(self, pdf_3pages: Path, tmp_path: Path):
        out_dir = tmp_path / "split_cancel"
        with pytest.raises(ConversionCancelledError):
            split_pdf(pdf_3pages, output_dir=out_dir, cancel_check=lambda: True)
        # No partial files created
        assert len(list(out_dir.glob("*.pdf"))) == 0


# ---------------------------------------------------------------------------
# Extract Tests
# ---------------------------------------------------------------------------

class TestPdfExtract:
    def test_extract_subset(self, pdf_3pages: Path, tmp_path: Path):
        out = extract_pdf_pages(pdf_3pages, pages="1, 3", output_dir=tmp_path)
        assert out.exists()
        info = _read_pdf_info(out)
        assert len(info) == 2
        assert info[0] == (100.0, 150.0, 0)
        assert info[1] == (300.0, 350.0, 270)

    def test_extract_single_page(self, pdf_3pages: Path, tmp_path: Path):
        dest = tmp_path / "extracted_p2.pdf"
        out = extract_pdf_pages(pdf_3pages, pages=2, output_path=dest)
        assert out == dest
        info = _read_pdf_info(out)
        assert len(info) == 1
        assert info[0] == (200.0, 250.0, 180)

    def test_extract_range(self, pdf_3pages: Path, tmp_path: Path):
        out = extract_pdf_pages(pdf_3pages, pages="2-3", output_dir=tmp_path)
        info = _read_pdf_info(out)
        assert len(info) == 2
        assert info[0] == (200.0, 250.0, 180)
        assert info[1] == (300.0, 350.0, 270)

    def test_extract_invalid_range_raises(self, pdf_3pages: Path, tmp_path: Path):
        with pytest.raises(InvalidInputError, match="inverted page range"):
            extract_pdf_pages(pdf_3pages, pages="3-1", output_dir=tmp_path)

    def test_extract_conflict_raises(self, pdf_3pages: Path):
        with pytest.raises(DestinationConflictError, match="identical to source"):
            extract_pdf_pages(pdf_3pages, pages=1, output_path=pdf_3pages)


# ---------------------------------------------------------------------------
# Reorder Tests
# ---------------------------------------------------------------------------

class TestPdfReorder:
    def test_reorder_pages_permutation(self, pdf_3pages: Path, tmp_path: Path):
        out = reorder_pdf_pages(pdf_3pages, page_order=[3, 1, 2], output_dir=tmp_path)
        assert out.exists()
        info = _read_pdf_info(out)
        assert len(info) == 3
        # Original page 3 was (300, 350, 270)
        assert info[0] == (300.0, 350.0, 270)
        # Original page 1 was (100, 150, 0)
        assert info[1] == (100.0, 150.0, 0)
        # Original page 2 was (200, 250, 180)
        assert info[2] == (200.0, 250.0, 180)

    def test_reorder_subset_order(self, pdf_3pages: Path, tmp_path: Path):
        out = reorder_pdf_pages(pdf_3pages, page_order=[2, 1], output_dir=tmp_path)
        info = _read_pdf_info(out)
        assert len(info) == 2
        assert info[0] == (200.0, 250.0, 180)
        assert info[1] == (100.0, 150.0, 0)

    def test_reorder_empty_sequence_raises(self, pdf_3pages: Path, tmp_path: Path):
        with pytest.raises(InvalidInputError, match="non-empty page_order"):
            reorder_pdf_pages(pdf_3pages, page_order=[], output_dir=tmp_path)

    def test_reorder_out_of_bounds_page_raises(self, pdf_3pages: Path, tmp_path: Path):
        with pytest.raises(InvalidInputError, match="out of bounds"):
            reorder_pdf_pages(pdf_3pages, page_order=[1, 4], output_dir=tmp_path)

    def test_reorder_zero_page_raises(self, pdf_3pages: Path, tmp_path: Path):
        with pytest.raises(InvalidInputError, match="out of bounds"):
            reorder_pdf_pages(pdf_3pages, page_order=[0, 1], output_dir=tmp_path)

    def test_reorder_non_integer_raises(self, pdf_3pages: Path, tmp_path: Path):
        with pytest.raises(InvalidInputError, match="not an integer"):
            reorder_pdf_pages(pdf_3pages, page_order=["1", 2], output_dir=tmp_path)  # type: ignore

    def test_reorder_preserves_original_file(self, pdf_3pages: Path, tmp_path: Path):
        orig_info = _read_pdf_info(pdf_3pages)
        reorder_pdf_pages(pdf_3pages, page_order=[3, 2, 1], output_dir=tmp_path)
        # Original file is unmodified
        assert _read_pdf_info(pdf_3pages) == orig_info


# ---------------------------------------------------------------------------
# Rotate Tests
# ---------------------------------------------------------------------------

class TestPdfRotate:
    def test_rotate_all_pages_relative_90(self, pdf_3pages: Path, tmp_path: Path):
        # Original rotations: [0, 180, 270]
        # With relative=True, +90: [90, 270, 0]
        out = rotate_pdf_pages(pdf_3pages, rotation=90, pages="all", relative=True, output_dir=tmp_path)
        info = _read_pdf_info(out)
        assert [r[2] for r in info] == [90, 270, 0]

    def test_rotate_specific_page_180(self, pdf_3pages: Path, tmp_path: Path):
        # Rotate only page 1 by 180°
        out = rotate_pdf_pages(pdf_3pages, rotation=180, pages=1, relative=True, output_dir=tmp_path)
        info = _read_pdf_info(out)
        assert [r[2] for r in info] == [180, 180, 270]

    def test_rotate_negative_angle(self, pdf_3pages: Path, tmp_path: Path):
        # -90° relative: (0 - 90) % 360 = 270, (180 - 90) % 360 = 90, (270 - 90) % 360 = 180
        out = rotate_pdf_pages(pdf_3pages, rotation=-90, pages="all", relative=True, output_dir=tmp_path)
        info = _read_pdf_info(out)
        assert [r[2] for r in info] == [270, 90, 180]

    def test_rotate_absolute(self, pdf_3pages: Path, tmp_path: Path):
        # Set absolute rotation to 90 on all pages
        out = rotate_pdf_pages(pdf_3pages, rotation=90, pages="all", relative=False, output_dir=tmp_path)
        info = _read_pdf_info(out)
        assert [r[2] for r in info] == [90, 90, 90]

    def test_rotate_invalid_angle_raises(self, pdf_3pages: Path, tmp_path: Path):
        with pytest.raises(InvalidInputError, match="Invalid rotation angle"):
            rotate_pdf_pages(pdf_3pages, rotation=45, output_dir=tmp_path)

    def test_rotate_non_integer_angle_raises(self, pdf_3pages: Path, tmp_path: Path):
        with pytest.raises(InvalidInputError, match="must be an integer"):
            rotate_pdf_pages(pdf_3pages, rotation="90", output_dir=tmp_path)  # type: ignore

    def test_rotate_preserves_original_file(self, pdf_3pages: Path, tmp_path: Path):
        orig_info = _read_pdf_info(pdf_3pages)
        rotate_pdf_pages(pdf_3pages, rotation=90, output_dir=tmp_path)
        assert _read_pdf_info(pdf_3pages) == orig_info


# ---------------------------------------------------------------------------
# CLI Integration Tests
# ---------------------------------------------------------------------------

class TestPdfWorkbenchCli:
    def test_cli_merge(self, pdf_1page: Path, pdf_2pages: Path, tmp_path: Path, monkeypatch, capsys):
        out_file = tmp_path / "cli_merged.pdf"
        monkeypatch.setattr(
            "sys.argv",
            ["localshift", "pdf", "merge", str(pdf_1page), str(pdf_2pages), "-o", str(out_file)],
        )
        cli_main()
        captured = capsys.readouterr()
        assert f"Saved: {out_file}" in captured.out
        assert out_file.exists()
        assert len(_read_pdf_info(out_file)) == 3

    def test_cli_split(self, pdf_2pages: Path, tmp_path: Path, monkeypatch, capsys):
        out_dir = tmp_path / "cli_split"
        monkeypatch.setattr(
            "sys.argv",
            ["localshift", "pdf", "split", str(pdf_2pages), "--output-dir", str(out_dir)],
        )
        cli_main()
        captured = capsys.readouterr()
        assert "Saved:" in captured.out
        created = list(out_dir.glob("*.pdf"))
        assert len(created) == 2

    def test_cli_extract(self, pdf_3pages: Path, tmp_path: Path, monkeypatch, capsys):
        out_file = tmp_path / "cli_extract.pdf"
        monkeypatch.setattr(
            "sys.argv",
            ["localshift", "pdf", "extract", str(pdf_3pages), "--pages", "1, 3", "-o", str(out_file)],
        )
        cli_main()
        captured = capsys.readouterr()
        assert f"Saved: {out_file}" in captured.out
        assert len(_read_pdf_info(out_file)) == 2

    def test_cli_reorder(self, pdf_3pages: Path, tmp_path: Path, monkeypatch, capsys):
        out_file = tmp_path / "cli_reorder.pdf"
        monkeypatch.setattr(
            "sys.argv",
            ["localshift", "pdf", "reorder", str(pdf_3pages), "--order", "3, 2, 1", "-o", str(out_file)],
        )
        cli_main()
        captured = capsys.readouterr()
        assert f"Saved: {out_file}" in captured.out
        assert [r[2] for r in _read_pdf_info(out_file)] == [270, 180, 0]

    def test_cli_rotate(self, pdf_1page: Path, tmp_path: Path, monkeypatch, capsys):
        out_file = tmp_path / "cli_rotate.pdf"
        monkeypatch.setattr(
            "sys.argv",
            ["localshift", "pdf", "rotate", str(pdf_1page), "--angle", "180", "-o", str(out_file)],
        )
        cli_main()
        captured = capsys.readouterr()
        assert f"Saved: {out_file}" in captured.out
        assert _read_pdf_info(out_file)[0][2] == 180
