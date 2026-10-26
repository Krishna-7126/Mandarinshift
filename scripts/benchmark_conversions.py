"""scripts/benchmark_conversions.py — Performance and throughput benchmarks for LocalShift.

Measures conversion latency, throughput, and memory consumption across:
1. Native Digital PDF → DOCX (Small, Medium, Large)
2. Scanned PDF → DOCX with OCR
3. Multi-image → Single PDF assembly
4. PDF → Image rasterization (PNG, JPEG)
5. Direct Image conversion routes (PNG → WebP, JPEG → PNG)
"""
from __future__ import annotations

import gc
import json
import os
import sys
import time
import tracemalloc
from pathlib import Path
from typing import Any

# Ensure localshift package is on path
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from localshift.converter import convert_request
from localshift.models import ConversionRequest
from localshift.documents.docx_builder import PdfToDocxReconstructor


def create_benchmark_files(output_dir: Path) -> dict[str, Path]:
    """Generate representative test files across size categories if not present."""
    output_dir.mkdir(parents=True, exist_ok=True)
    files: dict[str, Path] = {}

    import pypdfium2
    from PIL import Image, ImageDraw

    # 1. Images
    # Small image (512x512)
    img_sm = output_dir / "bench_sm.png"
    im1 = Image.new("RGB", (512, 512), color=(70, 130, 180))
    d1 = ImageDraw.Draw(im1)
    d1.text((30, 30), "Small Benchmark Image", fill=(255, 255, 255))
    im1.save(img_sm, format="PNG")
    files["image_small"] = img_sm

    # Medium image (1920x1080)
    img_md = output_dir / "bench_md.png"
    im2 = Image.new("RGB", (1920, 1080), color=(34, 139, 34))
    d2 = ImageDraw.Draw(im2)
    d2.text((50, 50), "Medium 1080p Benchmark Image", fill=(255, 255, 255))
    im2.save(img_md, format="PNG")
    files["image_medium"] = img_md

    # Multi-images for assembly (5 pages)
    multi_imgs = []
    for i in range(5):
        p = output_dir / f"assembly_{i+1}.png"
        im = Image.new("RGB", (800, 1000), color=(100 + i * 25, 80, 150))
        d = ImageDraw.Draw(im)
        d.text((40, 40), f"Assembly Page {i+1}", fill=(255, 255, 255))
        im.save(p, format="PNG")
        multi_imgs.append(p)
    files["multi_images"] = multi_imgs

    # 2. PDFs
    # Small PDF (1 page)
    pdf_sm = output_dir / "bench_sm.pdf"
    p_sm = pypdfium2.PdfDocument.new()
    page1 = p_sm.new_page(width=595, height=842)
    p_sm.save(pdf_sm)
    p_sm.close()
    files["pdf_small"] = pdf_sm

    # Use existing rich fixtures for medium and large PDFs
    fixtures_dir = REPO_ROOT / "tests" / "fixtures" / "documents"
    if (fixtures_dir / "doc_02_multipage_digital.pdf").is_file():
        files["pdf_digital_multipage"] = fixtures_dir / "doc_02_multipage_digital.pdf"
    else:
        files["pdf_digital_multipage"] = pdf_sm

    if (fixtures_dir / "doc_05_english_scan.pdf").is_file():
        files["pdf_scan_ocr"] = fixtures_dir / "doc_05_english_scan.pdf"

    if (fixtures_dir / "doc_18_dense_document.pdf").is_file():
        files["pdf_dense_digital"] = fixtures_dir / "doc_18_dense_document.pdf"

    return files


def run_single_benchmark(name: str, fn, *args, **kwargs) -> dict[str, Any]:
    """Execute a function while tracking execution time and peak memory."""
    gc.collect()
    tracemalloc.start()
    t0 = time.perf_counter()

    result = fn(*args, **kwargs)

    elapsed_s = time.perf_counter() - t0
    current_mem, peak_mem = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    gc.collect()

    return {
        "name": name,
        "elapsed_ms": round(elapsed_s * 1000, 2),
        "elapsed_s": round(elapsed_s, 3),
        "peak_mem_mb": round(peak_mem / (1024 * 1024), 2),
        "result": result,
    }


def main():
    bench_dir = REPO_ROOT / "tests" / "bench_workspace"
    out_dir = bench_dir / "outputs"
    out_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("LocalShift Milestone 16C Conversion Performance Benchmarks")
    print("=" * 60)

    files = create_benchmark_files(bench_dir)
    results = []

    # 1. Native Digital PDF → DOCX (doc_02_multipage_digital)
    if "pdf_digital_multipage" in files:
        src = files["pdf_digital_multipage"]
        req = ConversionRequest(source=src, target_format="docx", output_dir=out_dir)
        res = run_single_benchmark("PDF_to_DOCX (Multipage Digital)", convert_request, req)
        res["source_size_kb"] = round(src.stat().st_size / 1024, 2)
        out_p = res["result"].output_path
        res["output_size_kb"] = round(out_p.stat().st_size / 1024, 2)
        results.append(res)
        print(f"[PASS] {res['name']}: {res['elapsed_ms']} ms, Peak Mem: {res['peak_mem_mb']} MB")

    # 2. Dense Digital PDF → DOCX (doc_18_dense_document)
    if "pdf_dense_digital" in files:
        src = files["pdf_dense_digital"]
        req = ConversionRequest(source=src, target_format="docx", output_dir=out_dir)
        res = run_single_benchmark("PDF_to_DOCX (Dense Digital)", convert_request, req)
        res["source_size_kb"] = round(src.stat().st_size / 1024, 2)
        out_p = res["result"].output_path
        res["output_size_kb"] = round(out_p.stat().st_size / 1024, 2)
        results.append(res)
        print(f"[PASS] {res['name']}: {res['elapsed_ms']} ms, Peak Mem: {res['peak_mem_mb']} MB")

    # 3. Scanned PDF → DOCX with RapidOCR (doc_05_english_scan)
    if "pdf_scan_ocr" in files:
        src = files["pdf_scan_ocr"]
        req = ConversionRequest(source=src, target_format="docx", output_dir=out_dir, options={"ocr_mode": "force_ocr"})
        res = run_single_benchmark("PDF_to_DOCX (Scanned + RapidOCR)", convert_request, req)
        res["source_size_kb"] = round(src.stat().st_size / 1024, 2)
        out_p = res["result"].output_path
        res["output_size_kb"] = round(out_p.stat().st_size / 1024, 2)
        results.append(res)
        print(f"[PASS] {res['name']}: {res['elapsed_ms']} ms, Peak Mem: {res['peak_mem_mb']} MB")

    # 4. Image Conversion: PNG → WebP (Medium 1080p)
    if "image_medium" in files:
        src = files["image_medium"]
        req = ConversionRequest(source=src, target_format="webp", output_dir=out_dir)
        res = run_single_benchmark("Image (1080p PNG -> WebP)", convert_request, req)
        res["source_size_kb"] = round(src.stat().st_size / 1024, 2)
        out_p = res["result"].output_path
        res["output_size_kb"] = round(out_p.stat().st_size / 1024, 2)
        results.append(res)
        print(f"[PASS] {res['name']}: {res['elapsed_ms']} ms, Peak Mem: {res['peak_mem_mb']} MB")

    # 5. Image Conversion: PNG → JPEG (Small 512x512)
    if "image_small" in files:
        src = files["image_small"]
        req = ConversionRequest(source=src, target_format="jpeg", output_dir=out_dir)
        res = run_single_benchmark("Image (512px PNG -> JPEG)", convert_request, req)
        res["source_size_kb"] = round(src.stat().st_size / 1024, 2)
        out_p = res["result"].output_path
        res["output_size_kb"] = round(out_p.stat().st_size / 1024, 2)
        results.append(res)
        print(f"[PASS] {res['name']}: {res['elapsed_ms']} ms, Peak Mem: {res['peak_mem_mb']} MB")

    # 6. Multi-image Assembly -> Single PDF (5 pages)
    if "multi_images" in files:
        from localshift.documents.image_to_pdf import ImageToPdfConverter
        srcs = files["multi_images"]
        out = out_dir / "bench_assembled.pdf"
        res = run_single_benchmark("Images -> PDF (5 Pages Assembly)", ImageToPdfConverter.convert_images_to_pdf, srcs, out)
        res["source_size_kb"] = round(sum(p.stat().st_size for p in srcs) / 1024, 2)
        res["output_size_kb"] = round(out.stat().st_size / 1024, 2)
        results.append(res)
        print(f"[PASS] {res['name']}: {res['elapsed_ms']} ms, Peak Mem: {res['peak_mem_mb']} MB")

    # 7. PDF -> Image Rasterization (Multipage PNG export)
    if "pdf_digital_multipage" in files:
        from localshift.documents.pdf_image_exporter import PdfToImageExporter
        src = files["pdf_digital_multipage"]
        raster_dir = out_dir / "raster_out"
        res = run_single_benchmark("PDF -> PNG Rasterization (150 DPI)", PdfToImageExporter.export_pdf_to_images, src, raster_dir, "png", options={"dpi": 150})
        res["source_size_kb"] = round(src.stat().st_size / 1024, 2)
        out_paths = res["result"][0]
        res["output_size_kb"] = round(sum(p.stat().st_size for p in out_paths) / 1024, 2)
        results.append(res)
        print(f"[PASS] {res['name']}: {res['elapsed_ms']} ms, Peak Mem: {res['peak_mem_mb']} MB")

    # 8. PDF Suite: Compress PDF
    if "pdf_digital_multipage" in files:
        from localshift.documents.pdf_tools_engine import compress_pdf_file
        src = files["pdf_digital_multipage"]
        res = run_single_benchmark("PDF Tool: Compress PDF (High)", compress_pdf_file, src, compression_level="high", output_dir=out_dir)
        res["source_size_kb"] = round(src.stat().st_size / 1024, 2)
        out_p = res["result"]
        res["output_size_kb"] = round(out_p.stat().st_size / 1024, 2)
        results.append(res)
        print(f"[PASS] {res['name']}: {res['elapsed_ms']} ms, Peak Mem: {res['peak_mem_mb']} MB")

    # 9. PDF Suite: Crop PDF
    if "pdf_digital_multipage" in files:
        from localshift.documents.pdf_tools_engine import crop_pdf_pages
        src = files["pdf_digital_multipage"]
        res = run_single_benchmark("PDF Tool: Crop PDF Margins", crop_pdf_pages, src, margin_pt=18.0, output_dir=out_dir)
        res["source_size_kb"] = round(src.stat().st_size / 1024, 2)
        out_p = res["result"]
        res["output_size_kb"] = round(out_p.stat().st_size / 1024, 2)
        results.append(res)
        print(f"[PASS] {res['name']}: {res['elapsed_ms']} ms, Peak Mem: {res['peak_mem_mb']} MB")

    # 10. PDF Suite: PDF to Markdown
    if "pdf_digital_multipage" in files:
        from localshift.documents.pdf_tools_engine import pdf_to_markdown_file
        src = files["pdf_digital_multipage"]
        res = run_single_benchmark("PDF Tool: PDF to Markdown", pdf_to_markdown_file, src, output_dir=out_dir)
        res["source_size_kb"] = round(src.stat().st_size / 1024, 2)
        out_p = res["result"]
        res["output_size_kb"] = round(out_p.stat().st_size / 1024, 2)
        results.append(res)
        print(f"[PASS] {res['name']}: {res['elapsed_ms']} ms, Peak Mem: {res['peak_mem_mb']} MB")

    # 11. PDF Suite: Watermark PDF
    if "pdf_digital_multipage" in files:
        from localshift.documents.pdf_tools_engine import add_watermark_to_pdf
        src = files["pdf_digital_multipage"]
        res = run_single_benchmark("PDF Tool: Add Watermark (150 DPI)", add_watermark_to_pdf, src, text="CONFIDENTIAL", opacity=0.25, angle=45, output_dir=out_dir)
        res["source_size_kb"] = round(src.stat().st_size / 1024, 2)
        out_p = res["result"]
        res["output_size_kb"] = round(out_p.stat().st_size / 1024, 2)
        results.append(res)
        print(f"[PASS] {res['name']}: {res['elapsed_ms']} ms, Peak Mem: {res['peak_mem_mb']} MB")

    # 12. PDF Suite: HTML to PDF
    html_sample = bench_dir / "bench_sample.html"
    html_sample.write_text("<h1>Benchmark Report</h1><p>Offline HTML to PDF formatting test.</p>", encoding="utf-8")
    from localshift.documents.pdf_tools_engine import convert_html_to_pdf
    res = run_single_benchmark("PDF Tool: HTML to PDF", convert_html_to_pdf, html_sample, output_dir=out_dir)
    res["source_size_kb"] = round(html_sample.stat().st_size / 1024, 2)
    out_p = res["result"]
    res["output_size_kb"] = round(out_p.stat().st_size / 1024, 2)
    results.append(res)
    print(f"[PASS] {res['name']}: {res['elapsed_ms']} ms, Peak Mem: {res['peak_mem_mb']} MB")

    # 13. PDF Suite: PDF to Excel
    if "pdf_digital_multipage" in files:
        from localshift.documents.pdf_tools_engine import convert_pdf_to_excel
        src = files["pdf_digital_multipage"]
        res = run_single_benchmark("PDF Tool: PDF to Excel (.xlsx)", convert_pdf_to_excel, src, output_dir=out_dir)
        res["source_size_kb"] = round(src.stat().st_size / 1024, 2)
        out_p = res["result"]
        res["output_size_kb"] = round(out_p.stat().st_size / 1024, 2)
        results.append(res)
        print(f"[PASS] {res['name']}: {res['elapsed_ms']} ms, Peak Mem: {res['peak_mem_mb']} MB")

    # 14. PDF Suite: PDF to PowerPoint
    if "pdf_digital_multipage" in files:
        from localshift.documents.pdf_tools_engine import convert_pdf_to_powerpoint
        src = files["pdf_digital_multipage"]
        res = run_single_benchmark("PDF Tool: PDF to PowerPoint (.pptx)", convert_pdf_to_powerpoint, src, output_dir=out_dir)
        res["source_size_kb"] = round(src.stat().st_size / 1024, 2)
        out_p = res["result"]
        res["output_size_kb"] = round(out_p.stat().st_size / 1024, 2)
        results.append(res)
        print(f"[PASS] {res['name']}: {res['elapsed_ms']} ms, Peak Mem: {res['peak_mem_mb']} MB")

    # 15. PDF Suite: Sign PDF
    if "pdf_digital_multipage" in files:
        from localshift.documents.pdf_tools_engine import sign_pdf_document
        src = files["pdf_digital_multipage"]
        res = run_single_benchmark("PDF Tool: Sign PDF (Digital Seal)", sign_pdf_document, src, signature_text="Security Lead", output_dir=out_dir)
        res["source_size_kb"] = round(src.stat().st_size / 1024, 2)
        out_p = res["result"]
        res["output_size_kb"] = round(out_p.stat().st_size / 1024, 2)
        results.append(res)
        print(f"[PASS] {res['name']}: {res['elapsed_ms']} ms, Peak Mem: {res['peak_mem_mb']} MB")

    # 16. PDF Suite: Redact PDF
    if "pdf_digital_multipage" in files:
        from localshift.documents.pdf_tools_engine import redact_pdf_document
        src = files["pdf_digital_multipage"]
        res = run_single_benchmark("PDF Tool: Redact PDF (Purge & Rasterize)", redact_pdf_document, src, query_or_pattern="the", output_dir=out_dir)
        res["source_size_kb"] = round(src.stat().st_size / 1024, 2)
        out_p = res["result"]
        res["output_size_kb"] = round(out_p.stat().st_size / 1024, 2)
        results.append(res)
        print(f"[PASS] {res['name']}: {res['elapsed_ms']} ms, Peak Mem: {res['peak_mem_mb']} MB")

    # 17. PDF Suite: AI Summarizer
    if "pdf_digital_multipage" in files:
        from localshift.documents.pdf_tools_engine import summarize_pdf_document
        src = files["pdf_digital_multipage"]
        res = run_single_benchmark("PDF Tool: AI Summarizer (TextRank)", summarize_pdf_document, src, num_sentences=5, output_dir=out_dir)
        res["source_size_kb"] = round(src.stat().st_size / 1024, 2)
        out_p = res["result"]
        res["output_size_kb"] = round(out_p.stat().st_size / 1024, 2)
        results.append(res)
        print(f"[PASS] {res['name']}: {res['elapsed_ms']} ms, Peak Mem: {res['peak_mem_mb']} MB")

    print("\n" + "=" * 60)
    print("LocalShift Milestone 19 Production Benchmark Summary")
    print("=" * 60)
    header = f"{'Workflow / Target':<42} | {'Latency':<10} | {'Peak Mem':<10} | {'Output Size':<12}"
    print(header)
    print("-" * len(header))
    for r in results:
        print(f"{r['name']:<42} | {r['elapsed_ms']:>7} ms | {r['peak_mem_mb']:>7} MB | {r['output_size_kb']:>8} KB")

    # Save results to json for reporting
    json_path = REPO_ROOT / "docs" / "benchmarks_m19.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(
            [{k: v for k, v in r.items() if k != "result"} for r in results],
            f,
            indent=2,
        )
    print(f"\nSaved benchmark data to: {json_path}")


if __name__ == "__main__":
    main()
