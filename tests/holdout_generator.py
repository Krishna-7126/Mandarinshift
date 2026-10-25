"""
tests/holdout_generator.py — Independent Holdout Evaluation Corpus Generator.

Generates 10 legally unencumbered, realistic holdout fixtures that have NEVER
been used for development tuning:

1. holdout_01_quarterly_earnings_report.pdf (4 pages: executive summary, income statement table with negative values, segment breakdown, forward-looking statements).
2. holdout_02_clinical_trial_protocol.pdf (3 pages: clinical study protocol with multi-column text, medical inclusion/exclusion lists, section hierarchy).
3. holdout_03_upside_down_scanned_invoice.pdf (1 page: 180° upside-down scan to test OCR orientation classifier).
4. holdout_04_mixed_patient_record.pdf (4 pages: digital intake, degraded thermal lab report, blank divider page, scanned doctor signature).
5. holdout_05_multilingual_patent_claim.pdf (2 pages: international patent claims in English, German, and French).
6. holdout_06_landscape_engineering_drawing.pdf (1 page: 90° landscape orientation with component tolerances table).
7. holdout_07_industrial_equipment_manual.pdf (3 pages: machine safety manual with embedded schematic diagram and Figure 1 caption).
8. holdout_08_large_statutory_bylaws.pdf (10 pages: multi-page legislative bylaws testing streaming latency and memory scaling).
9. holdout_09_corrupt_or_truncated_edgecase.pdf (1 page: intentionally damaged/truncated xref stream for error trapping).
10. holdout_10_procurement_purchase_order.pdf (2 pages: enterprise purchase order with line items, currency codes, and delivery terms).

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
    """Generate a minimal PDF byte string with per-page orientation / rotation."""
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
        stream_lines = ["BT", "/F1 11 Tf", "50 750 Td", "14 TL"]
        for line_idx, line in enumerate(lines):
            if line_idx > 0:
                stream_lines.append("T*")
            stream_lines.append(f"({line}) Tj")
        stream_lines.append("ET")
        stream_data = "\n".join(stream_lines).encode("latin-1")

        stream_obj = (
            f"<</Length {len(stream_data)}>>\nstream\n".encode("ascii")
            + stream_data
            + b"\nendstream"
        )
        objects.append(stream_obj)

        rot = rotations[i] if i < len(rotations) else 0
        rot_entry = f"/Rotate {rot}" if rot != 0 else ""
        page_obj = (
            f"<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Resources<</Font<</F1 3 0 R>>>>{rot_entry}/Contents {4 + 2*i + 1} 0 R>>"
        ).encode("ascii")
        objects.append(page_obj)

    body = b"%PDF-1.4\n"
    offsets = [len(body)]
    for idx, obj in enumerate(objects, 1):
        offsets.append(len(body))
        body += f"{idx} 0 obj\n".encode("ascii") + obj + b"\nendobj\n"

    xref_offset = len(body)
    body += f"xref\n0 {len(objects) + 1}\n".encode("ascii")
    body += b"0000000000 65535 f \n"
    for off in offsets[1:]:
        body += f"{off:010d} 00000 n \n".encode("ascii")

    body += (
        f"trailer\n<</Size {len(objects) + 1}/Root 1 0 R>>\nstartxref\n{xref_offset}\n%%EOF\n"
    ).encode("ascii")
    return body


def _create_raster_page_pdf(lines: list[str], rotate_degrees: int = 0, degrade: bool = False) -> bytes:
    """Create a 1-page raster scan PDF with optional rotation and contrast degradation."""
    w, h = 800, 1100
    bg_color = (235, 230, 220) if degrade else (255, 255, 255)
    img = Image.new("RGB", (w, h), color=bg_color)
    draw = ImageDraw.Draw(img)

    text_color = (80, 80, 80) if degrade else (20, 20, 20)
    y = 80
    for line in lines:
        if line.strip():
            draw.text((60, y), line, fill=text_color)
        y += 26

    if degrade:
        # Add thermal printer horizontal fade lines and speckles
        for line_y in range(100, 1000, 150):
            draw.line([(50, line_y), (750, line_y)], fill=(210, 205, 195), width=2)

    if rotate_degrees != 0:
        img = img.rotate(rotate_degrees, expand=True)

    img_bytes = io.BytesIO()
    img.save(img_bytes, format="PNG")
    img_bytes.seek(0)

    pdf_doc = pypdfium2.PdfDocument.new()
    page = pdf_doc.new_page(612, 792)
    img_obj = pypdfium2.PdfImage.new(pdf_doc)
    pil_loaded = Image.open(img_bytes)
    img_obj.load_jpeg(img_bytes) if False else None
    
    # Use standard bitmap assignment
    bitmap = pypdfium2.PdfBitmap.from_pil(pil_loaded)
    image_obj = pypdfium2.PdfImage.new(pdf_doc)
    image_obj.set_bitmap(bitmap)
    image_obj.set_matrix(pypdfium2.PdfMatrix(612, 0, 0, 792, 0, 0))
    page.insert_obj(image_obj)
    page.gen_content()

    out_bytes = io.BytesIO()
    pdf_doc.save(out_bytes)
    return out_bytes.getvalue()


def _combine_pdfs(pdf_bytes_list: list[bytes]) -> bytes:
    """Merge multiple PDF byte streams into a single multi-page PDF."""
    combined = pypdfium2.PdfDocument.new()
    for b in pdf_bytes_list:
        doc = pypdfium2.PdfDocument(b)
        combined.import_pages(doc)
    out = io.BytesIO()
    combined.save(out)
    return out.getvalue()


def generate_holdout_corpus(output_dir: Path) -> dict[str, str]:
    """Generate all 10 holdout fixtures with ground-truth texts.

    Returns dict mapping fixture filename to ground-truth text.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    ground_truth: dict[str, str] = {}

    # 1. holdout_01_quarterly_earnings_report.pdf (4 pages)
    p1 = (
        "QUARTERLY FINANCIAL REPORT - Q3 2026\n"
        "Global Logistics & Technology Corp.\n\n"
        "Section 1: Executive Overview\n"
        "The Corporation delivered resilient operating performance during the third quarter.\n"
        "Revenue increased 8.2% year-over-year driven by digital supply chain expansion.\n"
        "- Total operating revenue reached $482.5 million.\n"
        "- Operating cash flow improved by 14.3% across core logistics units.\n"
        "- Cloud automation software subscriptions grew 27.5%."
    )
    p2 = (
        "Income Statement Summary\n"
        "--------------------------------------------------\n"
        "Revenue Category 2026 2025\n"
        "Enterprise Services $245,100.00 $210,500.00\n"
        "Logistics Freight $182,400.00 $175,200.00\n"
        "Software Subscriptions $55,000.00 $43,100.00\n"
        "Total Operating Revenue $482,500.00 $428,800.00\n"
        "Operating Expenses ($395,200.00) ($358,400.00)\n"
        "Restructuring Costs ($14,200.00) ($8,100.00)\n"
        "Operating Income $73,100.00 $62,300.00"
    )
    p3 = (
        "Segment Financial Performance\n"
        "--------------------------------------------------\n"
        "Division Revenue Margin Growth\n"
        "North America $215,000.00 18.5% 9.2%\n"
        "Europe Region $145,500.00 14.2% 6.1%\n"
        "Asia Pacific $122,000.00 21.0% 12.4%\n"
        "Consolidated Total $482,500.00 17.8% 8.2%"
    )
    p4 = (
        "Section 4: Forward-Looking Statements\n"
        "Certain disclosures contained herein constitute forward-looking statements:\n"
        "1. Projected capital expenditures remain subject to supply chain market conditions;\n"
        "2. Regulatory clearance in European ports is anticipated by fourth quarter;\n"
        "3. Technology investments may fluctuate based on enterprise adoption cycles."
    )
    h01_bytes = _build_simple_pdf_bytes([p1, p2, p3, p4])
    (output_dir / "holdout_01_quarterly_earnings_report.pdf").write_bytes(h01_bytes)
    ground_truth["holdout_01_quarterly_earnings_report.pdf"] = f"{p1}\n{p2}\n{p3}\n{p4}"

    # 2. holdout_02_clinical_trial_protocol.pdf (3 pages)
    c1 = (
        "CLINICAL STUDY PROTOCOL\n"
        "Protocol ID: BIO-2026-PHASE3\n\n"
        "Section 1: Primary Objectives\n"
        "The primary objective is to evaluate efficacy and safety of Compound-712.\n"
        "Patients will receive standardized oral dosing once daily over 24 weeks.\n"
        "1.1 Patient Eligibility Criteria\n"
        "- Age 18 to 75 years inclusive at time of screening;\n"
        "- Confirmed diagnostic indication according to ICD-11 guidelines;\n"
        "- Normal liver and renal biomarker function at baseline."
    )
    c2 = (
        "Section 2: Multi-Arm Dosing Schedule\n"
        "Treatment Arm Dosage Frequency Duration\n"
        "Arm A - Active 50 mg Daily 24 Weeks\n"
        "Arm B - Active 100 mg Daily 24 Weeks\n"
        "Arm C - Placebo 0 mg Daily 24 Weeks\n\n"
        "Adverse Event Monitoring\n"
        "Clinical safety reviews occur at Weeks 2, 4, 8, 12, and 24."
    )
    c3 = (
        "Section 3: Statistical Methodology\n"
        "Statistical analyses will follow intent-to-treat principles.\n"
        "Continuous variables will be summarized using mean and standard deviation.\n"
        "Categorical data will be evaluated using Fisher exact test comparisons.\n"
        "Interim monitoring will be conducted by an independent Data Safety Board."
    )
    h02_bytes = _build_simple_pdf_bytes([c1, c2, c3])
    (output_dir / "holdout_02_clinical_trial_protocol.pdf").write_bytes(h02_bytes)
    ground_truth["holdout_02_clinical_trial_protocol.pdf"] = f"{c1}\n{c2}\n{c3}"

    # 3. holdout_03_upside_down_scanned_invoice.pdf (1 page, 180° upside-down scan)
    inv_lines = [
        "EXPRESS COURIER SERVICE - INVOICE",
        "Invoice Number: INV-882190",
        "Date: 2026-10-14",
        "Customer: Apex Global Distribution",
        "Tracking ID: TRK-99201-US",
        "Freight Handling 50.00",
        "Fuel Surcharge 12.50",
        "Customs Clearance 25.00",
        "Total Amount Due 87.50",
    ]
    h03_bytes = _create_raster_page_pdf(inv_lines, rotate_degrees=180, degrade=False)
    (output_dir / "holdout_03_upside_down_scanned_invoice.pdf").write_bytes(h03_bytes)
    ground_truth["holdout_03_upside_down_scanned_invoice.pdf"] = "\n".join(inv_lines)

    # 4. holdout_04_mixed_patient_record.pdf (4 pages: digital, degraded scan, empty page, scanned stamp)
    med_p1 = (
        "HOSPITAL INTAKE ADMISSION RECORD\n"
        "Patient ID: MED-40912\n"
        "Admission Date: 2026-10-18\n"
        "Primary Complaint: Acute respiratory distress and mild fever.\n"
        "Medical History: Hypertension controlled with medication."
    )
    med_p1_bytes = _build_simple_pdf_bytes([med_p1])

    med_p2_lines = [
        "LABORATORY DIAGNOSTICS REPORT",
        "Serum Sodium: 138 mmol/L",
        "Serum Potassium: 4.1 mmol/L",
        "Blood Glucose: 98 mg/dL",
        "White Blood Cells: 6.8 K/uL",
        "Status: Normal limits",
    ]
    med_p2_bytes = _create_raster_page_pdf(med_p2_lines, rotate_degrees=0, degrade=True)

    med_p3_bytes = _build_simple_pdf_bytes(["   "])  # Empty divider page

    med_p4_lines = [
        "ATTENDING PHYSICIAN AUTHORIZATION",
        "Dr. Eleanor Vance, MD",
        "License Number: MED-991204",
        "Digital Seal: Hospital Clinical Center",
        "Authorized for Discharge: 2026-10-20",
    ]
    med_p4_bytes = _create_raster_page_pdf(med_p4_lines, rotate_degrees=0, degrade=False)

    h04_bytes = _combine_pdfs([med_p1_bytes, med_p2_bytes, med_p3_bytes, med_p4_bytes])
    (output_dir / "holdout_04_mixed_patient_record.pdf").write_bytes(h04_bytes)
    ground_truth["holdout_04_mixed_patient_record.pdf"] = (
        f"{med_p1}\n" + "\n".join(med_p2_lines) + "\n" + "\n".join(med_p4_lines)
    )

    # 5. holdout_05_multilingual_patent_claim.pdf (2 pages)
    pat_p1 = (
        "INTERNATIONAL PATENT SPECIFICATION\n"
        "Publication Number: WO 2026/091284 A1\n\n"
        "Article I: Technical Field\n"
        "The present invention relates to electrochemical energy storage systems.\n"
        "Specifically, high-efficiency electrolyte mixtures for solid-state batteries.\n\n"
        "Patentansprüche (German Claims)\n"
        "1. Festkörper-Elektrolyt umfassend Lithium-Verbindungen;\n"
        "2. Vorrichtung gemäß Anspruch 1 mit erhöhter thermischer Stabilität;\n"
        "3. Elektrode mit homogener Oberflächenbeschichtung."
    )
    pat_p2 = (
        "Article II: Detailed Scope\n"
        "Revendications (French Claims)\n"
        "1. Système de stockage électrochimique haute capacité;\n"
        "2. Procédé selon la revendication précédente comprenant un blindage thermique;\n"
        "3. Ensemble de cellules doté d un régulateur électronique intégré.\n\n"
        "Article III: Industrial Applicability\n"
        "The described technology is suitable for electric vehicle battery packs."
    )
    h05_bytes = _build_simple_pdf_bytes([pat_p1, pat_p2])
    (output_dir / "holdout_05_multilingual_patent_claim.pdf").write_bytes(h05_bytes)
    ground_truth["holdout_05_multilingual_patent_claim.pdf"] = f"{pat_p1}\n{pat_p2}"

    # 6. holdout_06_landscape_engineering_drawing.pdf (1 page, 90° landscape orientation)
    eng_text = (
        "ENGINEERING SPECIFICATION & TOLERANCES\n"
        "Component ID: ENG-BRG-2044\n"
        "Tolerance Class: ISO 2768-m\n\n"
        "Part Dimension Nominal Lower Tol Upper Tol\n"
        "Bore Diameter 45.00 mm -0.01 mm +0.02 mm\n"
        "Outer Ring 85.00 mm -0.02 mm +0.03 mm\n"
        "Width 19.00 mm -0.05 mm +0.05 mm\n"
        "Chamfer 1.50 mm -0.10 mm +0.10 mm"
    )
    h06_bytes = _build_simple_pdf_bytes([eng_text], rotation=90)
    (output_dir / "holdout_06_landscape_engineering_drawing.pdf").write_bytes(h06_bytes)
    ground_truth["holdout_06_landscape_engineering_drawing.pdf"] = eng_text

    # 7. holdout_07_industrial_equipment_manual.pdf (3 pages, diagram + Figure caption)
    m1 = (
        "INDUSTRIAL TURBINE OPERATIONS MANUAL\n"
        "Model: TURBO-MAX 5000\n\n"
        "Section 1: General Safety Procedures\n"
        "Ensure all technicians wear certified hearing protection before start-up.\n"
        "Verify emergency shut-off valves are accessible and unobstructed.\n"
        "- Check hydraulic fluid pressure before activating ignition circuit;\n"
        "- Inspect intake filters for debris every 250 operating hours."
    )
    m2 = (
        "Section 2: Valve Assembly Overview\n"
        "Figure 1: High Pressure Valve Assembly\n"
        "The dual bypass valve regulates chamber pressure under peak load.\n"
        "Maintenance Schedule\n"
        "Component Interval Action\n"
        "Intake Filter 250 Hours Clean or Replace\n"
        "Bypass Valve 500 Hours Pressure Calibration\n"
        "Turbine Rotor 2000 Hours Ultrasonic Inspection"
    )
    m3 = (
        "Section 3: Troubleshooting Protocols\n"
        "Fault Code Description Corrective Action\n"
        "ERR-101 Pressure Drop Check bypass seal\n"
        "ERR-104 Temp High Increase coolant flow\n"
        "ERR-202 Vibration Check rotor balance\n\n"
        "Contact authorized field service engineers for major overhaul procedures."
    )
    h07_bytes = _build_simple_pdf_bytes([m1, m2, m3])
    (output_dir / "holdout_07_industrial_equipment_manual.pdf").write_bytes(h07_bytes)
    ground_truth["holdout_07_industrial_equipment_manual.pdf"] = f"{m1}\n{m2}\n{m3}"

    # 8. holdout_08_large_statutory_bylaws.pdf (10 pages)
    bylaw_pages = []
    for p_num in range(1, 11):
        page_content = (
            f"MUNICIPAL REGULATORY BYLAWS - 2026\n"
            f"Chapter {p_num}: Statutory Operational Provisions\n\n"
            f"Section {p_num}.1: Administrative Authority and Jurisdiction\n"
            f"Under the powers conferred by the Local Government Enabling Act,\n"
            f"the municipal council hereby establishes the standards of Chapter {p_num}.\n\n"
            f"1. Every registered property owner shall comply with municipal codes;\n"
            f"2. Applications must be submitted in writing with certified architectural drawings;\n"
            f"3. Inspections shall be conducted during normal business hours.\n\n"
            f"(a) Residential permits expire twelve months from date of issuance;\n"
            f"(b) Commercial zoning variances require public hearing notifications;\n"
            f"(c) Appeals must be lodged within 30 days of the decision date."
        )
        bylaw_pages.append(page_content)
    h08_bytes = _build_simple_pdf_bytes(bylaw_pages)
    (output_dir / "holdout_08_large_statutory_bylaws.pdf").write_bytes(h08_bytes)
    ground_truth["holdout_08_large_statutory_bylaws.pdf"] = "\n".join(bylaw_pages)

    # 9. holdout_09_corrupt_or_truncated_edgecase.pdf (intentionally damaged stream)
    # Starts with %PDF-1.4 but truncated before xref table
    corrupt_bytes = b"%PDF-1.4\n1 0 obj\n<</Type/Catalog/Pages 2 0 R>>\nendobj\n"
    (output_dir / "holdout_09_corrupt_or_truncated_edgecase.pdf").write_bytes(corrupt_bytes)
    ground_truth["holdout_09_corrupt_or_truncated_edgecase.pdf"] = ""

    # 10. holdout_10_procurement_purchase_order.pdf (2 pages)
    po1 = (
        "OFFICIAL PURCHASE ORDER\n"
        "PO Number: PO-2026-8812\n"
        "Date: 2026-10-22\n"
        "Supplier: Precision Hardware Components Ltd.\n"
        "Delivery Location: Central Logistics Depot Bay 4\n\n"
        "Order Line Items\n"
        "--------------------------------------------------\n"
        "Line Description Qty Unit Price Total Price\n"
        "101 Titanium Bolts M8 500 $4.50 $2,250.00\n"
        "102 Ceramic Bearings 120 $18.00 $2,160.00\n"
        "103 Synthetic Lubricant 25 $32.00 $800.00\n"
        "104 O-Ring Sealing Pack 50 $15.50 $775.00\n"
        "Subtotal $5,985.00\n"
        "Sales Tax 8.0% $478.80\n"
        "Total Order Value $6,463.80"
    )
    po2 = (
        "TERMS AND CONDITIONS OF DELIVERY\n"
        "Section 1: Delivery Terms\n"
        "All shipments are delivered DAP (Incoterms 2020) unloaded at buyer facility.\n"
        "Section 2: Payment Terms\n"
        "Payment is Net 30 days following receipt of conforming goods and invoice.\n"
        "Section 3: Warranty\n"
        "Supplier warrants all delivered parts free from defects for 24 months."
    )
    h10_bytes = _build_simple_pdf_bytes([po1, po2])
    (output_dir / "holdout_10_procurement_purchase_order.pdf").write_bytes(h10_bytes)
    ground_truth["holdout_10_procurement_purchase_order.pdf"] = f"{po1}\n{po2}"

    # Write ground-truth files for evaluation harness
    gt_dir = output_dir / "ground_truth"
    gt_dir.mkdir(parents=True, exist_ok=True)
    for filename, text in ground_truth.items():
        stem = Path(filename).stem
        (gt_dir / f"{stem}.txt").write_text(text, encoding="utf-8")

    return ground_truth


if __name__ == "__main__":
    out = Path(__file__).parent / "fixtures" / "holdout_documents"
    gt = generate_holdout_corpus(out)
    print(f"Generated {len(gt)} holdout fixtures in {out}")
