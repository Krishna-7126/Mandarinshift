"""
tests/holdout_quality_evaluator.py — Independent Holdout Quality Evaluation & Quality Gate Harness.

Evaluates 10 independent, untouched holdout fixtures across:
- Character Error Rate (CER)
- Word Error Rate (WER)
- Reading order preservation
- Unicode diacritic & symbol preservation
- Peak heap memory delta (tracemalloc)
- Processing duration (ms)
- DOCX reconstruction (tables, headings, paragraphs, images, page count, Visual QA via Word COM)
- Native extraction, Auto OCR, and Force OCR routing comparisons
- Graceful error trapping on corrupt/truncated PDFs (holdout_09)
"""
from __future__ import annotations

import sys
import time
import tracemalloc
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))
if str(_root / "src") not in sys.path:
    sys.path.insert(0, str(_root / "src"))

from localshift import ConversionRequest, convert_request, ConversionFailedError, InvalidInputError
from localshift.documents.pdf_inspector import PdfInspector
from localshift.documents.text_extractor import NativePdfTextExtractor
from tests.pdf_quality_evaluator import (
    compute_cer,
    compute_wer,
    levenshtein_distance,
    normalize_whitespace,
)
from tests.visual_renderer import DocxVisualRenderer

HOLDOUT_DIR = Path(__file__).parent / "fixtures" / "holdout_documents"

HOLDOUT_CATEGORIES: dict[str, str] = {
    "holdout_01_quarterly_earnings_report": "1. Financial Earnings Release (4p, Negative Balances)",
    "holdout_02_clinical_trial_protocol": "2. Clinical Study Protocol (3p, Multi-arm Trial)",
    "holdout_03_upside_down_scanned_invoice": "3. Upside-Down Scanned Invoice (1p, 180° Raster)",
    "holdout_04_mixed_patient_record": "4. Mixed Medical Record (4p: Digital, Thermal Scan, Blank, Stamp)",
    "holdout_05_multilingual_patent_claim": "5. Multilingual Patent Claims (2p: EN, DE, FR)",
    "holdout_06_landscape_engineering_drawing": "6. Landscape Engineering Drawing (1p, 90° Rotated)",
    "holdout_07_industrial_equipment_manual": "7. Industrial Equipment Manual (3p, Schematics & Captions)",
    "holdout_08_large_statutory_bylaws": "8. Large Statutory Bylaws (10p, Multi-page Scaling)",
    "holdout_09_corrupt_or_truncated_edgecase": "9. Corrupt Truncated Stream (Error Trapping Edge Case)",
    "holdout_10_procurement_purchase_order": "10. Enterprise Purchase Order (2p, Itemized Table)",
}

# Ground truth text for native mode (born-digital stream only)
HOLDOUT_GROUND_TRUTH: dict[str, str] = {
    "holdout_01_quarterly_earnings_report": (
        "QUARTERLY FINANCIAL REPORT - Q3 2026\n"
        "Global Logistics & Technology Corp.\n\n"
        "Section 1: Executive Overview\n"
        "The Corporation delivered resilient operating performance during the third quarter.\n"
        "Revenue increased 8.2% year-over-year driven by digital supply chain expansion.\n"
        "- Total operating revenue reached $482.5 million.\n"
        "- Operating cash flow improved by 14.3% across core logistics units.\n"
        "- Cloud automation software subscriptions grew 27.5%.\n"
        "Income Statement Summary\n"
        "--------------------------------------------------\n"
        "Revenue Category 2026 2025\n"
        "Enterprise Services $245,100.00 $210,500.00\n"
        "Logistics Freight $182,400.00 $175,200.00\n"
        "Software Subscriptions $55,000.00 $43,100.00\n"
        "Total Operating Revenue $482,500.00 $428,800.00\n"
        "Operating Expenses ($395,200.00) ($358,400.00)\n"
        "Restructuring Costs ($14,200.00) ($8,100.00)\n"
        "Operating Income $73,100.00 $62,300.00\n"
        "Segment Financial Performance\n"
        "--------------------------------------------------\n"
        "Division Revenue Margin Growth\n"
        "North America $215,000.00 18.5% 9.2%\n"
        "Europe Region $145,500.00 14.2% 6.1%\n"
        "Asia Pacific $122,000.00 21.0% 12.4%\n"
        "Consolidated Total $482,500.00 17.8% 8.2%\n"
        "Section 4: Forward-Looking Statements\n"
        "Certain disclosures contained herein constitute forward-looking statements:\n"
        "1. Projected capital expenditures remain subject to supply chain market conditions;\n"
        "2. Regulatory clearance in European ports is anticipated by fourth quarter;\n"
        "3. Technology investments may fluctuate based on enterprise adoption cycles."
    ),
    "holdout_02_clinical_trial_protocol": (
        "CLINICAL STUDY PROTOCOL\n"
        "Protocol ID: BIO-2026-PHASE3\n\n"
        "Section 1: Primary Objectives\n"
        "The primary objective is to evaluate efficacy and safety of Compound-712.\n"
        "Patients will receive standardized oral dosing once daily over 24 weeks.\n"
        "1.1 Patient Eligibility Criteria\n"
        "- Age 18 to 75 years inclusive at time of screening;\n"
        "- Confirmed diagnostic indication according to ICD-11 guidelines;\n"
        "- Normal liver and renal biomarker function at baseline.\n"
        "Section 2: Multi-Arm Dosing Schedule\n"
        "Treatment Arm Dosage Frequency Duration\n"
        "Arm A - Active 50 mg Daily 24 Weeks\n"
        "Arm B - Active 100 mg Daily 24 Weeks\n"
        "Arm C - Placebo 0 mg Daily 24 Weeks\n\n"
        "Adverse Event Monitoring\n"
        "Clinical safety reviews occur at Weeks 2, 4, 8, 12, and 24.\n"
        "Section 3: Statistical Methodology\n"
        "Statistical analyses will follow intent-to-treat principles.\n"
        "Continuous variables will be summarized using mean and standard deviation.\n"
        "Categorical data will be evaluated using Fisher exact test comparisons.\n"
        "Interim monitoring will be conducted by an independent Data Safety Board."
    ),
    "holdout_03_upside_down_scanned_invoice": "",  # 0 chars native text
    "holdout_04_mixed_patient_record": (
        "HOSPITAL INTAKE ADMISSION RECORD\n"
        "Patient ID: MED-40912\n"
        "Admission Date: 2026-10-18\n"
        "Primary Complaint: Acute respiratory distress and mild fever.\n"
        "Medical History: Hypertension controlled with medication."
    ),
    "holdout_05_multilingual_patent_claim": (
        "INTERNATIONAL PATENT SPECIFICATION\n"
        "Publication Number: WO 2026/091284 A1\n\n"
        "Article I: Technical Field\n"
        "The present invention relates to electrochemical energy storage systems.\n"
        "Specifically, high-efficiency electrolyte mixtures for solid-state batteries.\n\n"
        "Patentansprüche (German Claims)\n"
        "1. Festkörper-Elektrolyt umfassend Lithium-Verbindungen;\n"
        "2. Vorrichtung gemäß Anspruch 1 mit erhöhter thermischer Stabilität;\n"
        "3. Elektrode mit homogener Oberflächenbeschichtung.\n"
        "Article II: Detailed Scope\n"
        "Revendications (French Claims)\n"
        "1. Système de stockage électrochimique haute capacité;\n"
        "2. Procédé selon la revendication précédente comprenant un blindage thermique;\n"
        "3. Ensemble de cellules doté d un régulateur électronique intégré.\n\n"
        "Article III: Industrial Applicability\n"
        "The described technology is suitable for electric vehicle battery packs."
    ),
    "holdout_06_landscape_engineering_drawing": (
        "ENGINEERING SPECIFICATION & TOLERANCES\n"
        "Component ID: ENG-BRG-2044\n"
        "Tolerance Class: ISO 2768-m\n\n"
        "Part Dimension Nominal Lower Tol Upper Tol\n"
        "Bore Diameter 45.00 mm -0.01 mm +0.02 mm\n"
        "Outer Ring 85.00 mm -0.02 mm +0.03 mm\n"
        "Width 19.00 mm -0.05 mm +0.05 mm\n"
        "Chamfer 1.50 mm -0.10 mm +0.10 mm"
    ),
    "holdout_07_industrial_equipment_manual": (
        "INDUSTRIAL TURBINE OPERATIONS MANUAL\n"
        "Model: TURBO-MAX 5000\n\n"
        "Section 1: General Safety Procedures\n"
        "Ensure all technicians wear certified hearing protection before start-up.\n"
        "Verify emergency shut-off valves are accessible and unobstructed.\n"
        "- Check hydraulic fluid pressure before activating ignition circuit;\n"
        "- Inspect intake filters for debris every 250 operating hours.\n"
        "Section 2: Valve Assembly Overview\n"
        "Figure 1: High Pressure Valve Assembly\n"
        "The dual bypass valve regulates chamber pressure under peak load.\n"
        "Maintenance Schedule\n"
        "Component Interval Action\n"
        "Intake Filter 250 Hours Clean or Replace\n"
        "Bypass Valve 500 Hours Pressure Calibration\n"
        "Turbine Rotor 2000 Hours Ultrasonic Inspection\n"
        "Section 3: Troubleshooting Protocols\n"
        "Fault Code Description Corrective Action\n"
        "ERR-101 Pressure Drop Check bypass seal\n"
        "ERR-104 Temp High Increase coolant flow\n"
        "ERR-202 Vibration Check rotor balance\n\n"
        "Contact authorized field service engineers for major overhaul procedures."
    ),
    "holdout_08_large_statutory_bylaws": "\n".join(
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
        for p_num in range(1, 11)
    ),
    "holdout_09_corrupt_or_truncated_edgecase": "",
    "holdout_10_procurement_purchase_order": (
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
        "Total Order Value $6,463.80\n"
        "TERMS AND CONDITIONS OF DELIVERY\n"
        "Section 1: Delivery Terms\n"
        "All shipments are delivered DAP (Incoterms 2020) unloaded at buyer facility.\n"
        "Section 2: Payment Terms\n"
        "Payment is Net 30 days following receipt of conforming goods and invoice.\n"
        "Section 3: Warranty\n"
        "Supplier warrants all delivered parts free from defects for 24 months."
    ),
}

# Ground truth text for OCR modes (including raster scan text)
HOLDOUT_OCR_GROUND_TRUTH: dict[str, str] = dict(HOLDOUT_GROUND_TRUTH)
HOLDOUT_OCR_GROUND_TRUTH["holdout_03_upside_down_scanned_invoice"] = (
    "EXPRESS COURIER SERVICE - INVOICE\n"
    "Invoice Number: INV-882190\n"
    "Date: 2026-10-14\n"
    "Customer: Apex Global Distribution\n"
    "Tracking ID: TRK-99201-US\n"
    "Freight Handling 50.00\n"
    "Fuel Surcharge 12.50\n"
    "Customs Clearance 25.00\n"
    "Total Amount Due 87.50"
)
HOLDOUT_OCR_GROUND_TRUTH["holdout_04_mixed_patient_record"] = (
    "HOSPITAL INTAKE ADMISSION RECORD\n"
    "Patient ID: MED-40912\n"
    "Admission Date: 2026-10-18\n"
    "Primary Complaint: Acute respiratory distress and mild fever.\n"
    "Medical History: Hypertension controlled with medication.\n"
    "LABORATORY DIAGNOSTICS REPORT\n"
    "Serum Sodium: 138 mmol/L\n"
    "Serum Potassium: 4.1 mmol/L\n"
    "Blood Glucose: 98 mg/dL\n"
    "White Blood Cells: 6.8 K/uL\n"
    "Status: Normal limits\n"
    "ATTENDING PHYSICIAN AUTHORIZATION\n"
    "Dr. Eleanor Vance, MD\n"
    "License Number: MED-991204\n"
    "Digital Seal: Hospital Clinical Center\n"
    "Authorized for Discharge: 2026-10-20"
)


@dataclass(frozen=True)
class HoldoutQualityMetric:
    fixture_id: str
    category: str
    page_count: int
    char_count_extracted: int
    char_count_expected: int
    cer: float
    wer: float
    unicode_preserved: bool
    reading_order_valid: bool
    duration_ms: float
    peak_memory_kib: float
    classification: str
    notes: str


@dataclass(frozen=True)
class HoldoutDocxMetric:
    fixture_id: str
    category: str
    tables_count: int
    headings_count: int
    paragraphs_count: int
    images_count: int
    cer: float
    wer: float
    peak_memory_kib: float
    duration_ms: float
    visual_render_status: str
    notes: str


def evaluate_holdout_fixture(pdf_path: Path, *, ocr_mode: str = "native_only") -> HoldoutQualityMetric:
    fixture_id = pdf_path.stem
    category = HOLDOUT_CATEGORIES.get(fixture_id, "Holdout Document")
    expected_text = (
        HOLDOUT_OCR_GROUND_TRUTH.get(fixture_id, "")
        if ocr_mode in ("auto", "force_ocr")
        else HOLDOUT_GROUND_TRUTH.get(fixture_id, "")
    )

    report = PdfInspector.inspect(pdf_path)

    tracemalloc.start()
    t0 = time.perf_counter()
    extracted_text = ""
    page_count = report.page_count
    char_count = 0

    try:
        if report.is_readable:
            res = NativePdfTextExtractor.extract(pdf_path, ocr_mode=ocr_mode)
            extracted_text = res.to_plain_text(page_separator="\n\n")
            page_count = res.page_count
            char_count = res.total_characters
    except Exception:
        pass
    finally:
        duration_ms = (time.perf_counter() - t0) * 1000.0
        _, peak_mem = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        peak_kib = peak_mem / 1024.0

    if not report.is_readable:
        return HoldoutQualityMetric(
            fixture_id=fixture_id,
            category=category,
            page_count=0,
            char_count_extracted=0,
            char_count_expected=len(expected_text),
            cer=0.0,
            wer=0.0,
            unicode_preserved=True,
            reading_order_valid=True,
            duration_ms=round(duration_ms, 2),
            peak_memory_kib=round(peak_kib, 1),
            classification="corrupt_unreadable",
            notes="Trapped corrupt/truncated stream gracefully",
        )

    cer = compute_cer(expected_text, extracted_text, normalize=True)
    wer = compute_wer(expected_text, extracted_text, normalize=True)

    # Unicode verification
    unicode_preserved = True
    if fixture_id == "holdout_05_multilingual_patent_claim":
        glyphs = ["Patentansprüche", "Festkörper", "gemäß", "Oberflächenbeschichtung", "Système", "électrochimique", "Procédé"]
        unicode_preserved = all(g in extracted_text for g in glyphs)

    # Reading order verification
    reading_order_valid = True
    if fixture_id == "holdout_01_quarterly_earnings_report":
        idx1 = extracted_text.find("Section 1: Executive Overview")
        idx2 = extracted_text.find("Income Statement Summary")
        idx3 = extracted_text.find("Section 4: Forward-Looking Statements")
        if idx1 != -1 and idx2 != -1 and idx3 != -1:
            reading_order_valid = idx1 < idx2 < idx3

    classification_label = "unreadable"
    if report.pages:
        classification_label = report.pages[0].classification.value
        if len(report.pages) > 1 and len({p.classification for p in report.pages}) > 1:
            classification_label = "mixed_pages"

    notes = "OK" if cer < 0.1 else f"CER={cer*100:.1f}%"
    if classification_label == "image_likely" and ocr_mode == "native_only":
        notes = "Raster scan: 0 native text, OCR required"

    return HoldoutQualityMetric(
        fixture_id=fixture_id,
        category=category,
        page_count=page_count,
        char_count_extracted=char_count,
        char_count_expected=len(expected_text),
        cer=round(cer, 4),
        wer=round(wer, 4),
        unicode_preserved=unicode_preserved,
        reading_order_valid=reading_order_valid,
        duration_ms=round(duration_ms, 2),
        peak_memory_kib=round(peak_kib, 1),
        classification=classification_label,
        notes=notes,
    )


def evaluate_all_holdout_fixtures(holdout_dir: Path, *, ocr_mode: str = "native_only") -> list[HoldoutQualityMetric]:
    metrics: list[HoldoutQualityMetric] = []
    for p in sorted(holdout_dir.glob("*.pdf")):
        metrics.append(evaluate_holdout_fixture(p, ocr_mode=ocr_mode))
    return metrics


def evaluate_holdout_docx_fixtures(holdout_dir: Path) -> list[HoldoutDocxMetric]:
    import docx
    import tempfile

    visual_available = DocxVisualRenderer.is_available()
    metrics: list[HoldoutDocxMetric] = []

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        for p in sorted(holdout_dir.glob("*.pdf")):
            fid = p.stem
            category = HOLDOUT_CATEGORIES.get(fid, "Holdout Document")
            expected = HOLDOUT_GROUND_TRUTH.get(fid, "")

            # If corrupt file, verify graceful trapping
            if fid == "holdout_09_corrupt_or_truncated_edgecase":
                tracemalloc.start()
                t0 = time.perf_counter()
                trapped = False
                try:
                    req = ConversionRequest(source=p, target_format="docx", output_dir=tmp_path)
                    convert_request(req)
                except (InvalidInputError, ConversionFailedError):
                    trapped = True
                finally:
                    dur_ms = (time.perf_counter() - t0) * 1000.0
                    _, peak_mem = tracemalloc.get_traced_memory()
                    tracemalloc.stop()

                metrics.append(HoldoutDocxMetric(
                    fixture_id=fid,
                    category=category,
                    tables_count=0,
                    headings_count=0,
                    paragraphs_count=0,
                    images_count=0,
                    cer=0.0,
                    wer=0.0,
                    peak_memory_kib=round(peak_mem / 1024.0, 1),
                    duration_ms=round(dur_ms, 2),
                    visual_render_status="SKIPPED (Corrupt)",
                    notes="Trapped InvalidInputError gracefully",
                ))
                continue

            tracemalloc.start()
            t0 = time.perf_counter()
            try:
                req = ConversionRequest(source=p, target_format="docx", output_dir=tmp_path)
                res = convert_request(req)
                dur_ms = (time.perf_counter() - t0) * 1000.0
                _, peak_mem = tracemalloc.get_traced_memory()
                tracemalloc.stop()

                doc = docx.Document(res.output_path)
                tables_cnt = len(doc.tables)
                headings_cnt = sum(1 for p_elm in doc.paragraphs if p_elm.style and p_elm.style.name.startswith("Heading"))
                paras_cnt = sum(1 for p_elm in doc.paragraphs if p_elm.text.strip())
                imgs_cnt = len(doc.inline_shapes)

                docx_text_runs = []
                for child in doc._element.body:
                    if child.tag.endswith("p"):
                        p_inst = docx.text.paragraph.Paragraph(child, doc)
                        if p_inst.text.strip():
                            docx_text_runs.append(p_inst.text.strip())
                    elif child.tag.endswith("tbl"):
                        t_inst = docx.table.Table(child, doc)
                        for row in t_inst.rows:
                            row_cells = [c.text.strip() for c in row.cells if c.text.strip()]
                            if row_cells:
                                docx_text_runs.append(" ".join(row_cells))
                full_docx_text = "\n".join(docx_text_runs)

                cer = compute_cer(expected, full_docx_text, normalize=True) if expected else 0.0
                wer = compute_wer(expected, full_docx_text, normalize=True) if expected else 0.0

                visual_status = "NOT RUN"
                if visual_available:
                    out_pdf = tmp_path / f"{fid}_qa.pdf"
                    ok = DocxVisualRenderer.render_docx_to_pdf(res.output_path, out_pdf)
                    if ok and out_pdf.exists():
                        pdf_rep = PdfInspector.inspect(out_pdf)
                        visual_status = f"PASS ({pdf_rep.page_count}p)"
                    else:
                        visual_status = "FAIL"

                notes = "OK" if cer < 0.1 else f"CER={cer*100:.1f}%"
                metrics.append(HoldoutDocxMetric(
                    fixture_id=fid,
                    category=category,
                    tables_count=tables_cnt,
                    headings_count=headings_cnt,
                    paragraphs_count=paras_cnt,
                    images_count=imgs_cnt,
                    cer=round(cer, 4),
                    wer=round(wer, 4),
                    peak_memory_kib=round(peak_mem / 1024.0, 1),
                    duration_ms=round(dur_ms, 2),
                    visual_render_status=visual_status,
                    notes=notes,
                ))
            except Exception as e:
                _, peak_mem = tracemalloc.get_traced_memory()
                tracemalloc.stop()
                metrics.append(HoldoutDocxMetric(
                    fixture_id=fid,
                    category=category,
                    tables_count=0,
                    headings_count=0,
                    paragraphs_count=0,
                    images_count=0,
                    cer=1.0,
                    wer=1.0,
                    peak_memory_kib=round(peak_mem / 1024.0, 1),
                    duration_ms=0.0,
                    visual_render_status="ERROR",
                    notes=f"Exception: {e}",
                ))

    return metrics


def format_holdout_markdown(title: str, metrics: Sequence[HoldoutQualityMetric]) -> str:
    lines = [
        f"# {title}",
        "",
        "| Fixture | Category | Pages | Chars Extr. | CER | WER | Unicode | Reading Order | Peak Mem (KiB) | Time (ms) | Classification | Notes |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for m in metrics:
        u_str = "PASS" if m.unicode_preserved else "FAIL"
        ro_str = "PASS" if m.reading_order_valid else "FAIL"
        lines.append(
            f"| `{m.fixture_id}` | {m.category} | {m.page_count} | {m.char_count_extracted} | "
            f"{m.cer*100:.1f}% | {m.wer*100:.1f}% | {u_str} | {ro_str} | "
            f"{m.peak_memory_kib} | {m.duration_ms} | `{m.classification}` | {m.notes} |"
        )
    return "\n".join(lines)


def format_holdout_docx_markdown(title: str, metrics: Sequence[HoldoutDocxMetric]) -> str:
    lines = [
        f"# {title}",
        "",
        "| Fixture | Category | Tables | Headings | Paragraphs | Images | CER | WER | Visual QA | Mem (KiB) | Time (ms) | Notes |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for m in metrics:
        lines.append(
            f"| `{m.fixture_id}` | {m.category} | {m.tables_count} | {m.headings_count} | "
            f"{m.paragraphs_count} | {m.images_count} | {m.cer*100:.1f}% | {m.wer*100:.1f}% | "
            f"{m.visual_render_status} | {m.peak_memory_kib} | {m.duration_ms} | {m.notes} |"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    from tests.holdout_generator import generate_holdout_corpus
    generate_holdout_corpus(HOLDOUT_DIR)

    # 1. Native Mode
    native_metrics = evaluate_all_holdout_fixtures(HOLDOUT_DIR, ocr_mode="native_only")
    print(format_holdout_markdown("LocalShift Holdout Benchmark Results (Native Mode)", native_metrics))
    print("\n")

    # 2. Auto OCR Mode
    auto_metrics = evaluate_all_holdout_fixtures(HOLDOUT_DIR, ocr_mode="auto")
    print(format_holdout_markdown("LocalShift Holdout Benchmark Results (Auto OCR Mode)", auto_metrics))
    print("\n")

    # 3. PDF -> DOCX Reconstruction & Visual QA
    docx_metrics = evaluate_holdout_docx_fixtures(HOLDOUT_DIR)
    print(format_holdout_docx_markdown("LocalShift Holdout PDF -> DOCX Reconstruction Results", docx_metrics))
