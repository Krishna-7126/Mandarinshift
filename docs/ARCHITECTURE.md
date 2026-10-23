# LocalShift — Architectural Overview

**Version:** 0.6.0 (Updated: Milestone LS-BE-006D)  
**System:** Offline-First Desktop Conversion Backend  

---

## 1. System Philosophy & Design Principles

LocalShift is built on three strict non-negotiables:
1. **Privacy First & 100% Offline:** Zero external network calls, zero analytics, zero document uploads. All conversion and OCR inference executes locally on the user's CPU.
2. **Untrusted Input Defense:** PDFs and user-submitted files are treated as untrusted data. Strict bounds are enforced on file sizes (250 MiB), page counts (2000 pages), rendering resolutions (72–400 DPI), and pixel memory ceilings (16 MP per page).
3. **Atomic & Collision-Safe I/O:** Conversions write to temporary files within safe directories and replace target files atomically. Existing files are never overwritten without explicit collision resolution (` (2)`, ` (3)`).

---

## 2. Layered Backend Architecture

```
[ Conversion Request / CLI / GUI / API ]
                   │
                   ▼
       [ Conversion Planner & Preflight ]
                   │
                   ▼
           [ AdapterRegistry ]
          /                 \
         ▼                   ▼
 [ PillowImageAdapter ]   [ PdfDocumentAdapter ]
                               │
               ┌───────────────┴───────────────┐
               ▼                               ▼
       [ PdfInspector ]             [ NativePdfTextExtractor ]
    (Structure & Classification)          /              \
                                         ▼                ▼
                                 [ Digital Flow ]   [ OCR Flow ]
                                        │                 │
                                  (PDFium Native)    [ PdfPageRenderer ]
                                                          │
                                                    [ RapidOcrEngine ]
                                                    (ONNX Runtime CPU)
                                                          │
                                                    [ reconstruct_reading_order ]
```

---

## 3. Core Subsystems

### A. Document Inspection (`localshift.documents.pdf_inspector.PdfInspector`)
- Fast, non-rasterizing structural inspection of PDFs using Google PDFium (`pypdfium2`).
- Inspects object streams and page metadata to classify pages:
  - `TEXT_PRESENT`: Significant native character count (≥ 40 chars).
  - `IMAGE_LIKELY`: Raster graphic scan (0 native chars, embedded images).
  - `MIXED_OR_UNCERTAIN`: Sparse text (< 40 chars) or vector graphics.
  - `EMPTY_OR_UNKNOWN`: Blank page (0 text, 0 images).
  - `UNREADABLE`: Damaged xref or corrupted page stream.

### B. Bounded Page Rendering (`localshift.documents.renderer.PdfPageRenderer`)
- High-performance rasterization to RGB NumPy arrays.
- Respects ISO 32000 maximum page dimensions (14,400 points).
- Clamps rendering DPI to safe bounds (72–400 DPI, default 200 DPI).
- Automatically downscales rendering scale if estimated pixel count exceeds `MAX_IMAGE_PIXELS` (16,000,000 pixels ~ 48 MB RAM buffer).
- Explicit lifecycle management ensures native PDFium bitmap buffers are closed immediately after array extraction.

### C. Offline OCR Engine (`localshift.documents.ocr.RapidOcrEngine`)
- Local, CPU-first inference using RapidOCR (v1.2.3) and ONNX Runtime CPU (v1.26.0).
- Bundles lightweight, high-accuracy PP-OCRv4 ONNX models (~13.7 MB total):
  - Detection: `ch_PP-OCRv4_det_infer.onnx`
  - Recognition: `ch_PP-OCRv4_rec_infer.onnx`
  - Direction classification: `ch_ppocr_mobile_v2.0_cls_infer.onnx`
- Thread-safe singleton caching avoids re-initializing ONNX inference sessions across multiple pages or documents.

### D. Reading-Order Reconstruction (`localshift.documents.ocr.reconstruct_reading_order`)
- Heuristic 2D line-grouping algorithm:
  - Filters out degenerate boxes.
  - Groups bounding boxes into horizontal lines if vertical overlap exceeds 45% of minimum line height.
  - Sorts lines vertically from top to bottom.
  - Sorts words horizontally within each line from left to right.
  - Emits clean, paragraph-separated UTF-8 plain text.

### E. Per-Page Extraction & Routing (`localshift.documents.text_extractor.NativePdfTextExtractor`)
- Supported modes:
  - `"auto"`: Intelligent per-page routing (`TEXT_PRESENT` → native extraction; `IMAGE_LIKELY` → OCR; `EMPTY_OR_UNKNOWN` → blank; `MIXED_OR_UNCERTAIN` → hybrid merge without duplication).
  - `"native_only"`: Fast digital extraction bypassing rasterization and OCR.
  - `"force_ocr"`: Forces full-page rasterization and OCR on all pages.

---

## 4. Resource & Security Controls

| Resource | Boundary / Ceiling | Mechanism |
|---|---|---|
| Max File Size | 250 MiB | Checked at conversion entry point (`convert_request`) |
| Max Pages | 2000 pages | Enforced in `NativePdfTextExtractor` before processing |
| Max Dimensions | 14,400 points | Verified in `PdfPageRenderer` |
| Max Raster Pixels | 16,000,000 pixels | Downscaled in `PdfPageRenderer` |
| Memory Limits | CPU inference | ONNX Runtime CPU provider; no GPU allocations |
| Cancellation | Cooperative | Polled between pages and before OCR rasterization |
| Output Atomicity | Atomic rename | Written to temporary file and renamed atomically |
