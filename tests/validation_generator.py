"""
tests/validation_generator.py — Independent unseen validation dataset generator.

Generates 10 separate evaluation PDF fixtures not used during initial benchmark tuning:
1. val_01_born_digital_contract.pdf: Legal agreement with clauses and signature block.
2. val_02_scanned_receipt.pdf: Low-resolution scanned store receipt with line items and totals.
3. val_03_mixed_report.pdf: 3-page mixed document (Page 1 digital, Page 2 scan, Page 3 digital).
4. val_04_three_column_newsletter.pdf: 3-column newsletter layout (sequential stream order).
5. val_05_complex_financial_table.pdf: Borderless multi-column accounting schedule with currency.
6. val_06_academic_paper.pdf: Academic paper with running headers, abstract, numbered sections, footer.
7. val_07_multilingual_legal.pdf: Multilingual text with German, French, Spanish, Nordic diacritics & symbols.
8. val_08_landscape_presentation.pdf: Landscape slide (/Rotate 90) with slide title and bullet points.
9. val_09_technical_manual_figures.pdf: Technical guide with embedded image and caption.
10. val_10_long_dense_manuscript.pdf: 5-page dense technical specification testing sustained pagination.

All fixtures are synthetic, 100% offline, deterministic, and legally unencumbered.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path
from typing import Optional

# Ensure project root is on sys.path
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from PIL import Image, ImageDraw, ImageFont
import pypdfium2

from tests.benchmark_generator import _build_simple_pdf_bytes


UNSEEN_GROUND_TRUTH: dict[str, str] = {
    "val_01_born_digital_contract": (
        "SOFTWARE LICENSE AGREEMENT\n\n"
        "This Agreement is entered into by and between LocalShift Project and the End User.\n\n"
        "1. Grant of License\n"
        "Licensor hereby grants a perpetual, non-exclusive license to execute the software locally.\n"
        "All data processing remains strictly on the client device without telemetry.\n\n"
        "2. Limitation of Liability\n"
        "The software is provided AS IS without warranties of any kind.\n\n"
        "Executed on October 24, 2026 by authorized representatives."
    ),
    "val_02_scanned_receipt": "",  # Pure raster image scan
    "val_03_mixed_report": (
        "EXECUTIVE EVALUATION REPORT\n"
        "Page 1: Project status and preliminary findings.\n\n"
        "Page 3: Conclusion and strategic recommendations for offline file tooling."
    ),
    "val_04_three_column_newsletter": (
        "Tech Briefing\nLocalShift releases v0.7.1.\nPrivacy first.\n\n"
        "Engineering Note\nModular adapters provide\nreliable conversion.\n\n"
        "Community Update\nZero network calls.\nFully offline operation."
    ),
    "val_05_complex_financial_table": (
        "Account Code    Description              Debit        Credit       Balance\n"
        "1010-01         Operating Cash Account   $45,200.00   $0.00        $45,200.00\n"
        "2010-02         Accounts Payable         $0.00        $12,450.00   $12,450.00\n"
        "3010-03         Retained Project Funds   $0.00        $32,750.00   $32,750.00\n"
        "4010-04         Software Development     $8,500.00    $0.00        $8,500.00"
    ),
    "val_06_academic_paper": (
        "Header: Journal of Offline Systems & Document Engineering\n\n"
        "Offline Reconstruction of Structured Documents from Portable Document Format\n\n"
        "Abstract: We examine algorithms for recovering headings, tables, and paragraphs without network dependencies.\n\n"
        "1. Introduction\n"
        "Document conversion requires strict fidelity to logical layout.\n\n"
        "2. Reconstruction Methodology\n"
        "Line clustering and heuristic bounds preserve semantic boundaries.\n\n"
        "Footer: Page 1 of 1"
    ),
    "val_07_multilingual_legal": (
        "INTERNATIONAL COMPLIANCE NOTICE\n\n"
        "German: Die Prüfung schützt persönliche Daten vor unbefugter Übertragung.\n"
        "French: Déclaration de conformité pour le traitement hors ligne sécurisé.\n"
        "Spanish: Garantía de privacidad absoluta en el procesamiento local de archivos.\n"
        "Nordic: Bekreftelse på sikker filbehandling og åpen kildekode.\n"
        "Financial: Total Fees = €1,250.00 / £980.00 / ¥150,000 / $1,400.00 (Tax incl. 19%)."
    ),
    "val_08_landscape_presentation": (
        "LocalShift Architecture Briefing\n\n"
        "Landscape Orientation Slide\n"
        "- Privacy First: 100% local CPU processing\n"
        "- Zero Telemetry: No network calls or cloud dependencies\n"
        "- Memory Safe: Bounded pixel allocation and safe handle lifecycles"
    ),
    "val_09_technical_manual_figures": (
        "System Architecture Manual\n\n"
        "Figure 1: Core Processing Pipeline\n\n"
        "The diagram above illustrates the directional adapter workflow from input validation to atomic write."
    ),
    "val_10_long_dense_manuscript": (
        "Page 1 of 5\nSection 1: Theoretical Foundations\nLong documents require sustained memory discipline and stable paragraph grouping across consecutive pages.\n\n"
        "Page 2 of 5\nSection 2: Execution Architecture\nEvery conversion step must maintain path reservations and clean temporary resource isolation.\n\n"
        "Page 3 of 5\nSection 3: Structural Extraction\nHeadings and paragraphs must not bleed across physical page break boundaries.\n\n"
        "Page 4 of 5\nSection 4: Memory Bounds and Ceilings\nBuffer allocations must remain flat over thousands of pages.\n\n"
        "Page 5 of 5\nSection 5: Final Verification\nVerification confirms deterministic output and zero data loss."
    ),
}

UNSEEN_OCR_GROUND_TRUTH: dict[str, str] = {
    **UNSEEN_GROUND_TRUTH,
    "val_02_scanned_receipt": (
        "LOCAL STORE RECEIPT\n"
        "Item 1: USB Cable $9.99\n"
        "Item 2: Adapter Hub $24.50\n"
        "Subtotal: $34.49\n"
        "Tax (8%): $2.76\n"
        "Total: $37.25\n"
        "Thank you for shopping local!"
    ),
}

UNSEEN_CATEGORIES: dict[str, str] = {
    "val_01_born_digital_contract": "1. Born-digital legal agreement",
    "val_02_scanned_receipt": "2. Scanned thermal receipt (raster image)",
    "val_03_mixed_report": "3. 3-Page mixed digital and scanned report",
    "val_04_three_column_newsletter": "4. 3-Column newsletter layout",
    "val_05_complex_financial_table": "5. Borderless accounting ledger table",
    "val_06_academic_paper": "6. Academic paper with header/footer",
    "val_07_multilingual_legal": "7. Multilingual international text",
    "val_08_landscape_presentation": "8. Landscape orientation presentation",
    "val_09_technical_manual_figures": "9. Technical figure with embedded graphic",
    "val_10_long_dense_manuscript": "10. 5-Page dense technical manuscript",
}


def generate_unseen_validation_fixtures(target_dir: Path) -> dict[str, Path]:
    """Generate all 10 deterministic unseen validation PDF fixtures in target_dir."""
    target_dir.mkdir(parents=True, exist_ok=True)
    fixtures: dict[str, Path] = {}

    # 1. Born-digital contract
    p1 = target_dir / "val_01_born_digital_contract.pdf"
    p1.write_bytes(_build_simple_pdf_bytes([UNSEEN_GROUND_TRUTH["val_01_born_digital_contract"]]))
    fixtures["val_01_born_digital_contract"] = p1

    # 2. Scanned store receipt (Pillow raster image rendered to PDF)
    p2 = target_dir / "val_02_scanned_receipt.pdf"
    img_rcpt = Image.new("RGB", (450, 650), "white")
    draw_rcpt = ImageDraw.Draw(img_rcpt)
    draw_rcpt.text((40, 40), "LOCAL STORE RECEIPT", fill="black")
    draw_rcpt.text((40, 80), "Date: 2026-10-24 14:30", fill="black")
    draw_rcpt.text((40, 120), "Item 1: USB Cable $9.99", fill="black")
    draw_rcpt.text((40, 160), "Item 2: Adapter Hub $24.50", fill="black")
    draw_rcpt.text((40, 220), "Subtotal: $34.49", fill="black")
    draw_rcpt.text((40, 260), "Tax (8%): $2.76", fill="black")
    draw_rcpt.text((40, 300), "Total: $37.25", fill="black")
    draw_rcpt.text((40, 360), "Thank you for shopping local!", fill="black")
    img_rcpt.save(p2, format="PDF")
    fixtures["val_02_scanned_receipt"] = p2

    # 3. 3-Page mixed report: Page 1 digital, Page 2 scanned stamp/certificate, Page 3 digital
    p3 = target_dir / "val_03_mixed_report.pdf"
    p3_p1_bytes = _build_simple_pdf_bytes(["EXECUTIVE EVALUATION REPORT\nPage 1: Project status and preliminary findings."])
    p3_p3_bytes = _build_simple_pdf_bytes(["Page 3: Conclusion and strategic recommendations for offline file tooling."])

    # Generate a certificate stamp scan for page 2
    img_cert = Image.new("RGB", (600, 800), "white")
    draw_cert = ImageDraw.Draw(img_cert)
    draw_cert.text((50, 60), "OFFICIAL AUDIT VERIFICATION CERTIFICATE", fill="black")
    draw_cert.text((50, 110), "Audited by: Independent QA Team", fill="black")
    draw_cert.text((50, 150), "Status: VERIFIED & COMPLIANT", fill="black")
    draw_cert.rectangle([40, 40, 550, 300], outline="black", width=2)
    buf_cert = io.BytesIO()
    img_cert.save(buf_cert, format="PDF")
    buf_cert.seek(0)

    doc_p1 = pypdfium2.PdfDocument(p3_p1_bytes)
    doc_p2 = pypdfium2.PdfDocument(buf_cert.getvalue())
    doc_p3 = pypdfium2.PdfDocument(p3_p3_bytes)

    doc_merged = pypdfium2.PdfDocument.new()
    doc_merged.import_pages(doc_p1, [0])
    doc_merged.import_pages(doc_p2, [0])
    doc_merged.import_pages(doc_p3, [0])
    doc_merged.save(p3)

    doc_p1.close()
    doc_p2.close()
    doc_p3.close()
    doc_merged.close()
    fixtures["val_03_mixed_report"] = p3

    # 4. Three-column newsletter
    p4 = target_dir / "val_04_three_column_newsletter.pdf"
    p4.write_bytes(_build_simple_pdf_bytes([UNSEEN_GROUND_TRUTH["val_04_three_column_newsletter"]]))
    fixtures["val_04_three_column_newsletter"] = p4

    # 5. Complex financial table (borderless accounting ledger)
    p5 = target_dir / "val_05_complex_financial_table.pdf"
    p5.write_bytes(_build_simple_pdf_bytes([UNSEEN_GROUND_TRUTH["val_05_complex_financial_table"]]))
    fixtures["val_05_complex_financial_table"] = p5

    # 6. Academic paper
    p6 = target_dir / "val_06_academic_paper.pdf"
    p6.write_bytes(_build_simple_pdf_bytes([UNSEEN_GROUND_TRUTH["val_06_academic_paper"]]))
    fixtures["val_06_academic_paper"] = p6

    # 7. Multilingual legal
    p7 = target_dir / "val_07_multilingual_legal.pdf"
    p7.write_bytes(_build_simple_pdf_bytes([UNSEEN_GROUND_TRUTH["val_07_multilingual_legal"]]))
    fixtures["val_07_multilingual_legal"] = p7

    # 8. Landscape presentation slide (/Rotate 90)
    p8 = target_dir / "val_08_landscape_presentation.pdf"
    p8.write_bytes(
        _build_simple_pdf_bytes([UNSEEN_GROUND_TRUTH["val_08_landscape_presentation"]], rotation=90)
    )
    fixtures["val_08_landscape_presentation"] = p8

    # 9. Technical manual with embedded figure
    p9 = target_dir / "val_09_technical_manual_figures.pdf"
    base_bytes_p9 = _build_simple_pdf_bytes([UNSEEN_GROUND_TRUTH["val_09_technical_manual_figures"]])
    doc_p9 = pypdfium2.PdfDocument(base_bytes_p9)
    page_p9 = doc_p9[0]
    img_obj_p9 = pypdfium2.PdfImage.new(doc_p9)
    pil_diag = Image.new("RGB", (200, 120), color=(40, 80, 140))
    draw_diag = ImageDraw.Draw(pil_diag)
    draw_diag.rectangle([15, 15, 185, 105], outline="white", width=2)
    draw_diag.text((25, 45), "Adapter Pipeline", fill="white")
    bmp_p9 = pypdfium2.PdfBitmap.from_pil(pil_diag)
    img_obj_p9.set_bitmap(bmp_p9)
    img_obj_p9.set_matrix(pypdfium2.PdfMatrix(200, 0, 0, 120, 100, 580))
    page_p9.insert_obj(img_obj_p9)
    page_p9.gen_content()
    doc_p9.save(p9)
    doc_p9.close()
    fixtures["val_09_technical_manual_figures"] = p9

    # 10. Long 5-page dense technical manuscript
    p10 = target_dir / "val_10_long_dense_manuscript.pdf"
    p10_pages = UNSEEN_GROUND_TRUTH["val_10_long_dense_manuscript"].split("\n\n")
    p10.write_bytes(_build_simple_pdf_bytes(p10_pages))
    fixtures["val_10_long_dense_manuscript"] = p10

    return fixtures


if __name__ == "__main__":
    out_dir = Path(__file__).parent / "fixtures" / "unseen_documents"
    generated = generate_unseen_validation_fixtures(out_dir)
    print(f"Generated {len(generated)} unseen validation fixtures in {out_dir}")
