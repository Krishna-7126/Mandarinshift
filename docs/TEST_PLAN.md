# LocalShift — Test Plan & Quality Assurance Strategy

**Version:** 0.7.2 (Updated: Milestone LS-BE-007C)  
**Test Suite Size:** 369 tests collected (366 passed, 3 skipped on non-admin Windows)  

---

## 1. Scope & Strategy

LocalShift uses a layered testing strategy focused strictly on backend correctness, safety, and reliability:
- **Unit Tests:** Fast, isolated testing of format normalization, magic-byte sniffing, options validation, and capability lookups.
- **Integration Tests:** End-to-end execution of `convert_request()` with real adapters, destination path collision resolution, atomic replacement, and cleanup verification.
- **Reliability & Concurrency Tests:** In-process path reservation locks, thread-safe job queue lifecycle, worker pool thread exhaustion, and cancel propagation.
- **Document & OCR Tests:** Offline OCR engine invocation, bounding box parsing, line grouping, memory-bounded rendering, DPI bounds, per-page routing (`auto`, `native_only`, `force_ocr`), text de-duplication, memory ownership, and language model audits.
- **Benchmark Corpus Quality Tests:** Deterministic evaluation of text extraction accuracy (Character Error Rate, Word Error Rate, Unicode preservation, reading order, and heap memory tracing) in both native and auto OCR modes across 18 benchmark categories.
- **Unseen Document Generalization Tests:** Independent validation against 10 unseen fixtures (`val_01` to `val_10`) never used for tuning, testing generalization on contracts, ledgers, receipts, multilingual text, and multi-page manuscripts.
- **Visual QA Fidelity Tests:** Headless rendering of generated `.docx` documents to PDF and high-DPI page images using local Microsoft Word COM automation or LibreOffice, with page count and visual integrity assertions.

---

## 2. Test File Inventory

| Test Module | Test Focus | Count | Key Assertions |
|---|---|---|---|
| [`tests/test_converter.py`](file:///Z:/LocalShift/tests/test_converter.py) | Core converter engine & legacy API | 63 | All image routes, collisions, alpha composite, atomic write |
| [`tests/test_adapters.py`](file:///Z:/LocalShift/tests/test_adapters.py) | Adapter contract & protocol checks | 31 | `ConversionAdapter` protocol, option specs, conflict detection |
| [`tests/test_jobs.py`](file:///Z:/LocalShift/tests/test_jobs.py) | Asynchronous JobQueue & batching | 80 | Lifecycle states, queue limits, eviction, thread safety |
| [`tests/test_planning.py`](file:///Z:/LocalShift/tests/test_planning.py) | Planning API & preflight validation | 30 | Capability discovery, `ConversionPlan`, point-in-time checks |
| [`tests/test_reliability.py`](file:///Z:/LocalShift/tests/test_reliability.py) | Concurrency & resource stress | 51 | Collision races, symlink safety, cancellation, memory safety |
| [`tests/test_document_foundation.py`](file:///Z:/LocalShift/tests/test_document_foundation.py) | Document container sniffing & fixtures | 5 | PDF `%PDF-` sniffing, DOCX OpenXML structure, 18 fixture generation |
| [`tests/test_pdf_extraction.py`](file:///Z:/LocalShift/tests/test_pdf_extraction.py) | PDF inspection & text extraction | 33 | Page counts, dimensions, rotations, text previews, adapter |
| [`tests/test_pdf_reliability.py`](file:///Z:/LocalShift/tests/test_pdf_reliability.py) | Benchmark quality & metrics | 18 | CER / WER calculations, benchmark corpus verification, latency |
| [`tests/test_pdf_ocr.py`](file:///Z:/LocalShift/tests/test_pdf_ocr.py) | Offline OCR engine, renderer & routing | 24 | RapidOCR detection, reading order, scanned PDF extraction, DPI bounds, de-duplication, memory safety, language audit |
| [`tests/test_pdf_docx.py`](file:///Z:/LocalShift/tests/test_pdf_docx.py) | PDF to DOCX document reconstruction | 23 | Born-digital, scanned, mixed, tables (bordered & borderless), headings, orientation, Unicode, image-caption flow, visual rendering QA |
| [`tests/test_unseen_validation.py`](file:///Z:/LocalShift/tests/test_unseen_validation.py) | Unseen document validation set | 7 | Generalization on legal contracts, financial ledgers, academic papers, multilingual text, manuscripts |

---

## 3. Benchmark Evaluation Harness (`tests/pdf_quality_evaluator.py`)

### Metrics Defined:
1. **Character Error Rate (CER):**
   $$\text{CER} = \frac{\text{Levenshtein}(\text{ref\_chars}, \text{hyp\_chars})}{\text{len}(\text{ref\_chars})}$$
2. **Word Error Rate (WER):**
   $$\text{WER} = \frac{\text{Levenshtein}(\text{ref\_words}, \text{hyp\_words})}{\text{len}(\text{ref\_words})}$$
3. **Strict vs. Normalized Scoring:**
   - **Normalized:** Standardizes whitespace runs (`\r\n`, `\t`, multiple spaces) to a single space. Preserves all punctuation, numbers, symbols, and diacritics.
   - **Strict:** Direct comparison without whitespace normalization.
4. **Memory Tracing:** Uses Python `tracemalloc` to track peak heap allocation delta during extraction.
5. **Execution Latency:** Uses `time.perf_counter()` to record extraction time in milliseconds.

### Reproduction Command:
```powershell
$env:PYTHONPATH = "src"
py -3.14 tests/pdf_quality_evaluator.py
```

---

## 4. Windows-Specific Testing Notes

1. **Path Normalization:** Windows paths are case-insensitive. All in-process reservations in `reserve_output_path()` normalize paths to lowercase canonical forms.
2. **File Locking:** Windows holds strict OS locks on open files (`PermissionError: [WinError 32]`). All file handles (Pillow images, PDFium documents, temporary files) must be closed in `finally` blocks before replacement or removal.
3. **Symlink Privileges:** Windows symlink creation requires Developer Mode or elevated privileges. Tests that create symlinks automatically check permissions and skip gracefully when running in standard non-elevated user mode.
