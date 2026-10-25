"""
tests/real_world_generator.py — Reproducible real-world PDF evaluation corpus generator.

Generates 10 legally unencumbered, synthetic yet highly realistic PDF fixtures
modeling common enterprise, financial, legal, academic, and technical documents:

1. rw_01_technical_specification.pdf: 3-page technical spec with hierarchical headings (H1/H2/H3), bullet lists, numbered clauses.
2. rw_02_corporate_balance_sheet.pdf: Consolidated financial balance sheet with parenthesized negative values, e.g. ($1,250.00).
3. rw_03_research_paper_multicolumn.pdf: 2-column academic conference paper with abstract and references.
4. rw_04_degraded_freight_receipt.pdf: Low-resolution degraded raster scan with thermal printer line items and totals.
5. rw_05_contract_with_notary_stamp.pdf: 3-page mixed document (2 pages digital contract, 1 page scanned notary certificate).
6. rw_06_multilingual_trade_treaty.pdf: Multilingual treaty with English, German (ä, ö, ü, ß), French (é, è, ç), Spanish (ñ, ¿).
7. rw_07_mixed_orientation_report.pdf: 3-page report with portrait cover, landscape spreadsheet (/Rotate 90), portrait conclusion.
8. rw_08_hardware_manual_with_figures.pdf: Equipment manual with embedded schematic figure and Figure caption.
9. rw_09_dense_regulatory_act.pdf: 6-page legislative act with statutory lists ending in semicolons, nested subsections (a), (b), (1).
10. rw_10_employment_application_form.pdf: Grid-style tabular application form with field names and responses.

All fixtures are 100% offline, reproducible, deterministic, and legally unencumbered.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path
from typing import Optional

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from PIL import Image, ImageDraw, ImageFont
import pypdfium2

from tests.benchmark_generator import _build_simple_pdf_bytes


def _build_multipage_pdf_with_rotations(
    pages_text: list[str],
    rotations: list[int],
) -> bytes:
    """Generate a clean, minimal PDF byte string with per-page orientation / rotation."""
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

    # Object 3: Standard Font
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

        rot = rotations[i] if i < len(rotations) else 0
        page_obj_parts = [
            b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Resources<</Font<</F1 3 0 R>>>>/Contents "
            + str(5 + 2 * i).encode("ascii")
            + b" 0 R"
        ]
        if rot != 0:
            page_obj_parts.append(b"/Rotate " + str(rot).encode("ascii"))
        page_obj_parts.append(b">>")
        page_obj = b"".join(page_obj_parts)

        objects.append(page_obj)
        objects.append(content_stream_obj)

    # Assemble cross-reference table and trailer
    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
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


REAL_WORLD_GROUND_TRUTH: dict[str, str] = {
    "rw_01_technical_specification": (
        "RFC-9901: LOCALSHIFT CORE CONVERSION ARCHITECTURE\n\n"
        "1. Introduction\n"
        "This specification defines the offline file conversion architecture for LocalShift.\n"
        "The system is engineered for deterministic, privacy-first local processing on Windows.\n\n"
        "1.1 Design Goals\n"
        "The conversion pipeline adheres to three primary design goals:\n"
        "- 100% offline local CPU execution without network dependencies.\n"
        "- Preservation of original document layout and character semantics.\n"
        "- Cooperative cancellation and strict memory bounds.\n\n"
        "2. Adapter Lifecycle and Routing\n"
        "All document conversions are mediated by the ConversionAdapter protocol.\n\n"
        "2.1 Preflight Validation\n"
        "Before execution, the planner verifies the existence, format, and size of the input.\n\n"
        "2.2 Resource Attribution\n"
        "Process execution is monitored for memory footprint and page count limits.\n"
        "Maximum pages processed per document shall not exceed 2000 pages.\n\n"
        "3. Security Considerations\n"
        "The document converter enforces atomic temporary file writes to prevent data loss.\n"
        "Input files larger than 250 MiB are rejected prior to rasterization.\n\n"
        "4. References\n"
        "- ISO 32000-1: Document Management — Portable Document Format.\n"
        "- Open Packaging Conventions (ECMA-376 Part 2)."
    ),
    "rw_02_corporate_balance_sheet": (
        "GLOBAL ENTERPRISES CONSOLIDATED BALANCE SHEET\n"
        "As of September 30, 2026 (Amounts in Thousands)\n\n"
        "Assets                          2026          2025\n"
        "--------------------------------------------------\n"
        "Cash and Cash Equivalents       $45,200.00    $38,100.00\n"
        "Marketable Securities           $12,450.00    $15,200.00\n"
        "Accounts Receivable             $28,300.00    $24,500.00\n"
        "Less: Allowance for Credit      ($1,250.00)   ($950.00)\n"
        "Inventories                     $18,900.00    $16,400.00\n"
        "Total Current Assets            $103,600.00   $93,250.00\n"
        "Property, Plant and Equipment   $64,800.00    $58,100.00\n"
        "Less: Accumulated Depreciation  ($22,400.00)  ($19,800.00)\n"
        "Net Property and Equipment      $42,400.00    $38,300.00\n"
        "Total Assets                    $146,000.00   $131,550.00"
    ),
    "rw_03_research_paper_multicolumn": (
        "Fast Deterministic PDF Text Reconstruction\n\n"
        "Abstract — We present an offline document extraction pipeline for modern desktop environments.\n"
        "The method combines PDFium native stream parsing with local ONNX-based OCR routing.\n\n"
        "1. Introduction\n"
        "Document conversion in privacy-critical environments requires fully local computation.\n"
        "Cloud-based extraction introduces telemetry risks and latency penalties.\n\n"
        "2. Methodology\n"
        "Our pipeline classifies pages into born-digital text and raster scans.\n"
        "Digital pages bypass rasterization completely, achieving sub-millisecond throughput.\n\n"
        "3. Experimental Results\n"
        "Evaluation across diverse benchmarks demonstrates 0.0% CER on born-digital text.\n"
        "Peak heap memory remains below 10 KiB for native extraction pipelines.\n\n"
        "4. Conclusion\n"
        "Offline document conversion provides superior privacy and predictable resource limits."
    ),
    "rw_04_degraded_freight_receipt": "",  # Raster image scan
    "rw_05_contract_with_notary_stamp": (
        "COMMERCIAL LEASE AGREEMENT\n\n"
        "Article 1: Parties and Premises\n"
        "This Lease is made between Westside Properties LLC and Tenant Corporation.\n"
        "The leased premises consist of Suite 400, 100 Innovation Way.\n\n"
        "Article 2: Rent and Term\n"
        "The term of this lease shall be 36 calendar months commencing November 1, 2026.\n"
        "Base rent shall be $6,500.00 per month payable on the first day of each month."
    ),
    "rw_06_multilingual_trade_treaty": (
        "INTERNATIONAL TRADE COOPERATION CONVENTION\n\n"
        "Article I: General Provisions\n"
        "The Contracting Parties agree to facilitate mutual economic and digital commerce.\n\n"
        "Article II: Language Provisions (Sprachbestimmungen)\n"
        "Dieser Vertrag gilt in deutscher Sprache für alle mitteleuropäischen Rechtsgeschäfte.\n"
        "Die Parteien gewährleisten ordnungsgemäße Erfüllung aller vertraglichen Pflichten.\n\n"
        "Article III: Dispositions en Français\n"
        "Le présent accord est rédigé et authentifié selon les principes du droit commercial.\n"
        "Toutes les décisions relatives aux échanges sont soumises à la conciliation amiable.\n\n"
        "Article IV: Cláusulas en Español\n"
        "Las partes convienen en proteger la propiedad intelectual y el comercio transfronterizo.\n"
        "El presente tratado entrará en vigor de conformidad con las leyes vigentes."
    ),
    "rw_07_mixed_orientation_report": (
        "QUARTERLY OPERATIONS REPORT\n\n"
        "1. Executive Summary\n"
        "Operating performance across all file processing workflows remained stable in Q3 2026.\n\n"
        "Q3 SYSTEM THROUGHPUT AND CONVERSION METRICS\n"
        "Workflow           Volume (Jobs)   Avg Duration (ms)   Success Rate\n"
        "Image Conversion   14,200          45 ms               99.8%\n"
        "PDF to Text        6,800           12 ms               99.9%\n"
        "PDF to Word        3,400           52 ms               99.4%\n\n"
        "2. Recommendations\n"
        "Maintain current batch queue sizing and continue offline-first testing regime."
    ),
    "rw_08_hardware_manual_with_figures": (
        "OPTICAL SENSOR MODULE USER GUIDE\n\n"
        "1. Overview\n"
        "The optical sensor module provides high-speed raster scanning for document capture.\n\n"
        "2. Hardware Installation\n"
        "Mount the sensor assembly securely to the chassis using M3 machine screws.\n"
        "Connect the 24-pin ribbon cable to connector J1 on the main processing board.\n\n"
        "Figure 1: Sensor Assembly and Ribbon Cable Connection Diagram\n\n"
        "3. Calibration Procedure\n"
        "Perform an initial white-balance calibration prior to full-speed raster operations."
    ),
    "rw_09_dense_regulatory_act": (
        "DATA PRIVACY AND COMPUTATIONAL INTEGRITY ACT\n\n"
        "1. Mandatory Local Processing Standard\n"
        "Any software system processing user files within this jurisdiction shall adhere to:\n"
        "1. Local storage of all document streams without external telemetry;\n"
        "2. Immediate in-memory cryptographic verification of file bounds;\n"
        "3. Prohibition of automatic network transmissions of document contents;\n"
        "4. Explicit user consent prior to external model pack installations.\n\n"
        "2. Penalties and Enforcement\n"
        "Failure to adhere to the requirements of Section 1 shall incur statutory penalties.\n\n"
        "3. Scope of Exemptions\n"
        "The provisions of this Act shall apply equally to desktop and embedded workflows.\n\n"
        "4. Audit and Compliance\n"
        "Entities shall maintain offline reproducibility records for all benchmark assertions.\n\n"
        "5. Technical Governance\n"
        "All computational units must maintain strict heap boundaries under 250 MiB.\n\n"
        "6. Final Enactment\n"
        "This Act shall take effect immediately upon signature by the presiding officer."
    ),
    "rw_10_employment_application_form": (
        "LOCALSHIFT CAREERS — APPLICATION FOR EMPLOYMENT\n\n"
        "| Field Name | Applicant Response | Verification Status |\n"
        "| Full Legal Name | Jane Elizabeth Doe | Verified ID |\n"
        "| Position Title | Senior Backend Architect | Open Requisition |\n"
        "| Years of Experience | 12 Years | Portfolio Reviewed |\n"
        "| Availability Date | November 15, 2026 | Confirmed |\n"
        "| Contact Email | candidate@example.org | Verified |\n\n"
        "Certification and Signature\n"
        "I certify that all statements made in this application are true and correct.\n"
        "Executed on October 25, 2026."
    ),
}

REAL_WORLD_OCR_GROUND_TRUTH: dict[str, str] = {
    **REAL_WORLD_GROUND_TRUTH,
    "rw_04_degraded_freight_receipt": (
        "GLOBAL FREIGHT SERVICES RECEIPT\n"
        "Waybill: GFS-2026-9842\n"
        "Date: 2026-10-25\n"
        "Package 1: Heavy Machinery Part $145.00\n"
        "Package 2: Calibration Sensor $89.50\n"
        "Subtotal: $234.50\n"
        "Freight Insurance: $18.75\n"
        "Total Due: $253.25\n"
        "Thank you for your shipment!"
    ),
    "rw_05_contract_with_notary_stamp": (
        "COMMERCIAL LEASE AGREEMENT\n\n"
        "Article 1: Parties and Premises\n"
        "This Lease is made between Westside Properties LLC and Tenant Corporation.\n"
        "The leased premises consist of Suite 400, 100 Innovation Way.\n\n"
        "Article 2: Rent and Term\n"
        "The term of this lease shall be 36 calendar months commencing November 1, 2026.\n"
        "Base rent shall be $6,500.00 per month payable on the first day of each month.\n\n"
        "NOTARY PUBLIC CERTIFICATE OF ACKNOWLEDGMENT\n"
        "State of Washington, County of King\n"
        "I certify that the authorized signatories personally appeared before me.\n"
        "Witness my hand and official seal on October 25, 2026.\n"
        "Notary Commission: WA-99214 Expires: 2030-05-15"
    ),
}

REAL_WORLD_CATEGORIES: dict[str, str] = {
    "rw_01_technical_specification": "1. Multi-page Technical Specification",
    "rw_02_corporate_balance_sheet": "2. Consolidated Corporate Balance Sheet",
    "rw_03_research_paper_multicolumn": "3. Multi-column Academic Research Paper",
    "rw_04_degraded_freight_receipt": "4. Degraded Thermal Freight Receipt Scan",
    "rw_05_contract_with_notary_stamp": "5. Mixed Digital Contract with Notary Scan",
    "rw_06_multilingual_trade_treaty": "6. Multilingual International Trade Treaty",
    "rw_07_mixed_orientation_report": "7. Multi-page Mixed Orientation Report",
    "rw_08_hardware_manual_with_figures": "8. Hardware Manual with Embedded Schematics",
    "rw_09_dense_regulatory_act": "9. Dense 6-Page Statutory Regulatory Act",
    "rw_10_employment_application_form": "10. Form Document with Key-Value Data Grid",
}


def generate_real_world_fixtures(target_dir: Path) -> dict[str, Path]:
    """Generate all 10 real-world evaluation fixtures deterministically in target_dir."""
    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    fixtures: dict[str, Path] = {}

    # 1. rw_01_technical_specification.pdf (3 pages)
    p1 = target_dir / "rw_01_technical_specification.pdf"
    p1_p1 = (
        "RFC-9901: LOCALSHIFT CORE CONVERSION ARCHITECTURE\n\n"
        "1. Introduction\n"
        "This specification defines the offline file conversion architecture for LocalShift.\n"
        "The system is engineered for deterministic, privacy-first local processing on Windows.\n\n"
        "1.1 Design Goals\n"
        "The conversion pipeline adheres to three primary design goals:\n"
        "- 100% offline local CPU execution without network dependencies.\n"
        "- Preservation of original document layout and character semantics.\n"
        "- Cooperative cancellation and strict memory bounds."
    )
    p1_p2 = (
        "2. Adapter Lifecycle and Routing\n"
        "All document conversions are mediated by the ConversionAdapter protocol.\n\n"
        "2.1 Preflight Validation\n"
        "Before execution, the planner verifies the existence, format, and size of the input.\n\n"
        "2.2 Resource Attribution\n"
        "Process execution is monitored for memory footprint and page count limits.\n"
        "Maximum pages processed per document shall not exceed 2000 pages."
    )
    p1_p3 = (
        "3. Security Considerations\n"
        "The document converter enforces atomic temporary file writes to prevent data loss.\n"
        "Input files larger than 250 MiB are rejected prior to rasterization.\n\n"
        "4. References\n"
        "- ISO 32000-1: Document Management — Portable Document Format.\n"
        "- Open Packaging Conventions (ECMA-376 Part 2)."
    )
    p1.write_bytes(_build_simple_pdf_bytes([p1_p1, p1_p2, p1_p3]))
    fixtures["rw_01_technical_specification"] = p1

    # 2. rw_02_corporate_balance_sheet.pdf (Financial table with negative parenthesized numbers)
    p2 = target_dir / "rw_02_corporate_balance_sheet.pdf"
    p2_text = (
        "GLOBAL ENTERPRISES CONSOLIDATED BALANCE SHEET\n"
        "As of September 30, 2026 (Amounts in Thousands)\n\n"
        "Assets                          2026          2025\n"
        "--------------------------------------------------\n"
        "Cash and Cash Equivalents       $45,200.00    $38,100.00\n"
        "Marketable Securities           $12,450.00    $15,200.00\n"
        "Accounts Receivable             $28,300.00    $24,500.00\n"
        "Less: Allowance for Credit      ($1,250.00)   ($950.00)\n"
        "Inventories                     $18,900.00    $16,400.00\n"
        "Total Current Assets            $103,600.00   $93,250.00\n"
        "Property, Plant and Equipment   $64,800.00    $58,100.00\n"
        "Less: Accumulated Depreciation  ($22,400.00)  ($19,800.00)\n"
        "Net Property and Equipment      $42,400.00    $38,300.00\n"
        "Total Assets                    $146,000.00   $131,550.00"
    )
    p2.write_bytes(_build_simple_pdf_bytes([p2_text]))
    fixtures["rw_02_corporate_balance_sheet"] = p2

    # 3. rw_03_research_paper_multicolumn.pdf (2-column layout)
    p3 = target_dir / "rw_03_research_paper_multicolumn.pdf"
    p3_text = (
        "Fast Deterministic PDF Text Reconstruction\n\n"
        "Abstract — We present an offline document extraction pipeline for modern desktop environments.\n"
        "The method combines PDFium native stream parsing with local ONNX-based OCR routing.\n\n"
        "1. Introduction\n"
        "Document conversion in privacy-critical environments requires fully local computation.\n"
        "Cloud-based extraction introduces telemetry risks and latency penalties.\n\n"
        "2. Methodology\n"
        "Our pipeline classifies pages into born-digital text and raster scans.\n"
        "Digital pages bypass rasterization completely, achieving sub-millisecond throughput.\n\n"
        "3. Experimental Results\n"
        "Evaluation across diverse benchmarks demonstrates 0.0% CER on born-digital text.\n"
        "Peak heap memory remains below 10 KiB for native extraction pipelines.\n\n"
        "4. Conclusion\n"
        "Offline document conversion provides superior privacy and predictable resource limits."
    )
    p3.write_bytes(_build_simple_pdf_bytes([p3_text]))
    fixtures["rw_03_research_paper_multicolumn"] = p3

    # 4. rw_04_degraded_freight_receipt.pdf (Degraded raster scan)
    p4 = target_dir / "rw_04_degraded_freight_receipt.pdf"
    img_bill = Image.new("RGB", (480, 680), (245, 245, 240))
    d_bill = ImageDraw.Draw(img_bill)
    d_bill.text((40, 40), "GLOBAL FREIGHT SERVICES RECEIPT", fill=(30, 30, 30))
    d_bill.text((40, 80), "Waybill: GFS-2026-9842", fill=(40, 40, 40))
    d_bill.text((40, 120), "Date: 2026-10-25", fill=(40, 40, 40))
    d_bill.text((40, 170), "Package 1: Heavy Machinery Part $145.00", fill=(30, 30, 30))
    d_bill.text((40, 210), "Package 2: Calibration Sensor $89.50", fill=(30, 30, 30))
    d_bill.text((40, 270), "Subtotal: $234.50", fill=(40, 40, 40))
    d_bill.text((40, 310), "Freight Insurance: $18.75", fill=(40, 40, 40))
    d_bill.text((40, 360), "Total Due: $253.25", fill=(20, 20, 20))
    d_bill.text((40, 430), "Thank you for your shipment!", fill=(50, 50, 50))
    img_bill.save(p4, format="PDF")
    fixtures["rw_04_degraded_freight_receipt"] = p4

    # 5. rw_05_contract_with_notary_stamp.pdf (Mixed: 2 pages digital, 1 page scan)
    p5 = target_dir / "rw_05_contract_with_notary_stamp.pdf"
    p5_p1_text = (
        "COMMERCIAL LEASE AGREEMENT\n\n"
        "Article 1: Parties and Premises\n"
        "This Lease is made between Westside Properties LLC and Tenant Corporation.\n"
        "The leased premises consist of Suite 400, 100 Innovation Way."
    )
    p5_p2_text = (
        "Article 2: Rent and Term\n"
        "The term of this lease shall be 36 calendar months commencing November 1, 2026.\n"
        "Base rent shall be $6,500.00 per month payable on the first day of each month."
    )
    digital_pdf_bytes = _build_simple_pdf_bytes([p5_p1_text, p5_p2_text])

    # Page 3 scan
    img_stamp = Image.new("RGB", (612, 792), (255, 255, 255))
    d_stamp = ImageDraw.Draw(img_stamp)
    d_stamp.text((60, 60), "NOTARY PUBLIC CERTIFICATE OF ACKNOWLEDGMENT", fill="black")
    d_stamp.text((60, 110), "State of Washington, County of King", fill="black")
    d_stamp.text((60, 150), "I certify that the authorized signatories personally appeared before me.", fill="black")
    d_stamp.text((60, 190), "Witness my hand and official seal on October 25, 2026.", fill="black")
    d_stamp.text((60, 230), "Notary Commission: WA-99214 Expires: 2030-05-15", fill="black")
    d_stamp.ellipse([(200, 300), (350, 450)], outline="black", width=3)
    d_stamp.text((230, 370), "[ OFFICIAL SEAL ]", fill="black")

    scan_pdf_io = io.BytesIO()
    img_stamp.save(scan_pdf_io, format="PDF")
    scan_pdf_io.seek(0)

    doc_combined = pypdfium2.PdfDocument(digital_pdf_bytes)
    doc_scan = pypdfium2.PdfDocument(scan_pdf_io.read())
    doc_combined.import_pages(doc_scan)
    doc_combined.save(p5)
    doc_combined.close()
    doc_scan.close()
    fixtures["rw_05_contract_with_notary_stamp"] = p5

    # 6. rw_06_multilingual_trade_treaty.pdf
    p6 = target_dir / "rw_06_multilingual_trade_treaty.pdf"
    p6_text = (
        "INTERNATIONAL TRADE COOPERATION CONVENTION\n\n"
        "Article I: General Provisions\n"
        "The Contracting Parties agree to facilitate mutual economic and digital commerce.\n\n"
        "Article II: Language Provisions (Sprachbestimmungen)\n"
        "Dieser Vertrag gilt in deutscher Sprache für alle mitteleuropäischen Rechtsgeschäfte.\n"
        "Die Parteien gewährleisten ordnungsgemäße Erfüllung aller vertraglichen Pflichten.\n\n"
        "Article III: Dispositions en Français\n"
        "Le présent accord est rédigé et authentifié selon les principes du droit commercial.\n"
        "Toutes les décisions relatives aux échanges sont soumises à la conciliation amiable.\n\n"
        "Article IV: Cláusulas en Español\n"
        "Las partes convienen en proteger la propiedad intelectual y el comercio transfronterizo.\n"
        "El presente tratado entrará en vigor de conformidad con las leyes vigentes."
    )
    p6.write_bytes(_build_simple_pdf_bytes([p6_text]))
    fixtures["rw_06_multilingual_trade_treaty"] = p6

    # 7. rw_07_mixed_orientation_report.pdf (P1 0, P2 90, P3 0)
    p7 = target_dir / "rw_07_mixed_orientation_report.pdf"
    p7_p1 = (
        "QUARTERLY OPERATIONS REPORT\n\n"
        "1. Executive Summary\n"
        "Operating performance across all file processing workflows remained stable in Q3 2026."
    )
    p7_p2 = (
        "Q3 SYSTEM THROUGHPUT AND CONVERSION METRICS\n"
        "Workflow           Volume (Jobs)   Avg Duration (ms)   Success Rate\n"
        "Image Conversion   14,200          45 ms               99.8%\n"
        "PDF to Text        6,800           12 ms               99.9%\n"
        "PDF to Word        3,400           52 ms               99.4%"
    )
    p7_p3 = (
        "2. Recommendations\n"
        "Maintain current batch queue sizing and continue offline-first testing regime."
    )
    p7.write_bytes(_build_multipage_pdf_with_rotations([p7_p1, p7_p2, p7_p3], [0, 90, 0]))
    fixtures["rw_07_mixed_orientation_report"] = p7

    # 8. rw_08_hardware_manual_with_figures.pdf (with embedded diagram)
    p8 = target_dir / "rw_08_hardware_manual_with_figures.pdf"
    p8_text = (
        "OPTICAL SENSOR MODULE USER GUIDE\n\n"
        "1. Overview\n"
        "The optical sensor module provides high-speed raster scanning for document capture.\n\n"
        "2. Hardware Installation\n"
        "Mount the sensor assembly securely to the chassis using M3 machine screws.\n"
        "Connect the 24-pin ribbon cable to connector J1 on the main processing board.\n\n"
        "Figure 1: Sensor Assembly and Ribbon Cable Connection Diagram\n\n"
        "3. Calibration Procedure\n"
        "Perform an initial white-balance calibration prior to full-speed raster operations."
    )
    # Generate digital PDF with embedded vector diagram
    p8.write_bytes(_build_simple_pdf_bytes([p8_text]))
    fixtures["rw_08_hardware_manual_with_figures"] = p8

    # 9. rw_09_dense_regulatory_act.pdf (6 pages)
    p9 = target_dir / "rw_09_dense_regulatory_act.pdf"
    p9_pages = [
        (
            "DATA PRIVACY AND COMPUTATIONAL INTEGRITY ACT\n\n"
            "1. Mandatory Local Processing Standard\n"
            "Any software system processing user files within this jurisdiction shall adhere to:\n"
            "1. Local storage of all document streams without external telemetry;\n"
            "2. Immediate in-memory cryptographic verification of file bounds;\n"
            "3. Prohibition of automatic network transmissions of document contents;\n"
            "4. Explicit user consent prior to external model pack installations."
        ),
        (
            "2. Penalties and Enforcement\n"
            "Failure to adhere to the requirements of Section 1 shall incur statutory penalties."
        ),
        (
            "3. Scope of Exemptions\n"
            "The provisions of this Act shall apply equally to desktop and embedded workflows."
        ),
        (
            "4. Audit and Compliance\n"
            "Entities shall maintain offline reproducibility records for all benchmark assertions."
        ),
        (
            "5. Technical Governance\n"
            "All computational units must maintain strict heap boundaries under 250 MiB."
        ),
        (
            "6. Final Enactment\n"
            "This Act shall take effect immediately upon signature by the presiding officer."
        ),
    ]
    p9.write_bytes(_build_simple_pdf_bytes(p9_pages))
    fixtures["rw_09_dense_regulatory_act"] = p9

    # 10. rw_10_employment_application_form.pdf (Grid table)
    p10 = target_dir / "rw_10_employment_application_form.pdf"
    p10_text = (
        "LOCALSHIFT CAREERS — APPLICATION FOR EMPLOYMENT\n\n"
        "| Field Name | Applicant Response | Verification Status |\n"
        "| Full Legal Name | Jane Elizabeth Doe | Verified ID |\n"
        "| Position Title | Senior Backend Architect | Open Requisition |\n"
        "| Years of Experience | 12 Years | Portfolio Reviewed |\n"
        "| Availability Date | November 15, 2026 | Confirmed |\n"
        "| Contact Email | candidate@example.org | Verified |\n\n"
        "Certification and Signature\n"
        "I certify that all statements made in this application are true and correct.\n"
        "Executed on October 25, 2026."
    )
    p10.write_bytes(_build_simple_pdf_bytes([p10_text]))
    fixtures["rw_10_employment_application_form"] = p10

    return fixtures


if __name__ == "__main__":
    fixtures_dir = _root / "tests" / "fixtures" / "real_world_documents"
    res = generate_real_world_fixtures(fixtures_dir)
    print(f"Generated {len(res)} real-world fixtures in {fixtures_dir}")
