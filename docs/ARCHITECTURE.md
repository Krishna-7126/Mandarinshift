# LocalShift — Architectural Overview

**Version:** 0.12.0 (Updated: Milestone LS-BE-012)  
**System:** Offline-First Desktop Conversion Backend  

---

## 1. System Philosophy & Design Principles

LocalShift is built on three strict non-negotiables:
1. **Privacy First & 100% Offline:** Zero external network calls, zero analytics, zero document uploads. All conversion, document rendering, and OCR inference executes locally on the user's host.
2. **Untrusted Input Defense:** PDFs, DOCX files, images, and user-submitted files are treated as untrusted data. Strict bounds are enforced on file sizes (250 MiB), container structure (zip integrity and XML schema validation), page counts (2000 pages), rendering resolutions (72–400 DPI), and pixel memory ceilings (16 MP per page/image).
3. **Atomic & Collision-Safe I/O:** Conversions write to temporary files within safe directories and replace target files atomically. Existing files are never overwritten without explicit collision resolution (` (1)`, ` (2)`). Source files are opened read-only and never mutated.

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
          /        │        \            \
         ▼         ▼         ▼            ▼
[ PillowAdapter ] [ ImageToPdfAdapter ] [ DocxToPdfAdapter ]
   (img ⇄ img)       │                     │
                     │              (LibreOffice / Word COM)
                     ▼                     │
           [ PdfDocumentAdapter ] ─────────┘
                     │
      ┌──────────────┼──────────────┐
      ▼              ▼              ▼
  [ TXT Target ] [ DOCX Target ] [ PNG/JPEG Target ]
  (TextExtractor)(Reconstructor) (ImageExporter)
   /     \          /   │   \       │
  ▼       ▼        ▼    ▼    ▼    [ Renderer ]
  [Native] [OCR] [Tables][Images]   │
     │        │     │             (Pillow)
   (PDFium) [Renderer]
              │
          [RapidOCR]
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
- Hardened buffer memory ownership (`OWNDATA: True`) eliminates use-after-free risks when closing native PDFium bitmaps.

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

### F. Structured DOCX Document Reconstruction (`localshift.documents.docx_builder.PdfToDocxReconstructor`)
- Reconstructs digital, scanned, and mixed PDFs into editable Microsoft Word (.docx) documents.
- **Headings:** Recovers multi-level headings (Levels 1–3) based on font size metrics, section numbering (`1.`, `1.1`), and uppercase title patterns.
- **Paragraphs:** Conservative line joining groups visual lines into coherent paragraphs while respecting list bullets (`- `, `* `, `• `) and sentence boundaries.
- **Tables:** Detects tabular structures from separator rules or aligned multi-column data, outputting native formatted Word tables (`Table Grid`).
- **Images:** Extracts embedded raster graphics from digital pages and embeds them as scalable Word pictures.
- **Orientation & Page Sequence:** Configures section orientation to landscape for rotated pages (90°/270°) and preserves multi-page sequence with page breaks.

### G. Offline DOCX → PDF Document Rendering (`localshift.documents.docx_renderer.DocxToPdfRenderer`)
- Dedicated rendering engine converting Microsoft Word documents (.docx) to PDF.
- **Backend Strategies:**
  - *LibreOffice Headless:* Uses `soffice.exe --headless --convert-to pdf` with an isolated user profile (`-env:UserInstallation`) to ensure sandbox isolation and eliminate profile lock contention.
  - *Microsoft Word COM Automation:* On Windows, uses PowerShell COM automation with non-interactive execution, read-only opening, and prompt suppression (`DisplayAlerts = 0`).
- **Dynamic Route Availability:** Checks system environment at capability query time. Does not advertise `("docx", "pdf")` unless at least one valid backend is discovered.
- **Sandboxed Execution & Immutability:** Source files are copied to an isolated temporary sandbox (`localshift_docx_render_*`). Renderers execute exclusively against sandboxed copies; source files are never opened with write locks or modified.
- **Subprocess Supervision:** Monitored via non-blocking polling loops supporting cooperative cancellation, strict timeouts (clamped 5–300s, default 60s), forced process termination (`kill()`), and complete temporary artifact cleanup.

### H. PDF Page Image Exporter (`localshift.documents.pdf_image_exporter.PdfToImageExporter`)
- High-resolution, bounded offline rasterization exporting single or multipage PDFs into individual PNG or JPEG image files.
- **Page Selection:** Supports `"all"`, single page, range (`"1-5"`), and comma-delimited lists (`"1, 3, 5"`), with strict bounds and syntax validation.
- **Batch Multipage Placement:** Manages atomic placement and collision protection across all generated pages. Single-page PDFs default to `{stem}.{ext}`, while multipage exports number pages sequentially (`{stem}_page_{page}.{ext}`).
- **Pattern Customization:** Supports configurable patterns with `{stem}`, `{page}`, `{page_count}`, and `{ext}` tokens, rejecting path traversal attempts.
- **Resource Ceiling:** Clamps DPI (72–400) and limits maximum raster pixels per page (16 MP) via `PdfPageRenderer`.

### I. Image → PDF Assembly Engine (`localshift.documents.image_to_pdf.ImageToPdfConverter` & `ImageToPdfAdapter`)
- Dedicated engine converting raster images (PNG, JPEG, WebP, BMP, TIFF) to PDF, supporting both 1:1 conversion and ordered multipage assembly.
- **Layout & Dimension Modes:**
  - `"original"` / `"fit_to_image"` matches exact image aspect ratio and dimensions at specified DPI.
  - Standard page sizes (`"a4"`, `"letter"`), with portrait/landscape or auto orientation matching aspect ratios.
  - `"contain"` mode scales proportionally within margins; `"cover"` mode fills printable area with centered cropping.
- **Compositing & Format Normalization:**
  - Strips alpha channels against configurable RGB background fill (`(255, 255, 255)` default).
  - Normalizes CMYK, Grayscale, and Paletted modes to RGB before writing.
  - Respects EXIF orientation tags (`ImageOps.exif_transpose`).
- **Ordered Multipage Assembly:**
  - Assembles multiple sources sequentially (`additional_sources`) with cooperative cancellation and memory limits per image.
  - Custom output naming via `output_name` with reservation and atomic placement.

### J. PDF Workbench Engine (`localshift.documents.pdf_workbench.PdfWorkbench`)
- High-performance, fully offline PDF structure and page manipulation engine.
- **Merge (`merge_pdfs`):** Sequentially combines multiple PDF files into one ordered output document with full page dimension, rotation, and media box preservation.
- **Split (`split_pdf`):** Extracts pages into individual single-page PDFs using flexible page syntax and configurable output naming tokens (`{stem}`, `{page}`, `{page_count}`, `{ext}`).
- **Extract (`extract_pdf_pages`):** Extracts page subsets into a single target PDF document without content re-encoding.
- **Reorder (`reorder_pdf_pages`):** Rearranges pages based on validated 1-based index sequences.
- **Rotate (`rotate_pdf_pages`):** Rotates selected or all pages by 90°, 180°, or 270° with relative (`(current + angle) % 360`) or absolute modes.
- **Integrity & Concurrency Controls:** Preflight inspection via `PdfInspector`, input source immutability, volume-local temporary file generation, in-process destination reservations (`reserve_output_path`), atomic replacement (`os.replace`), and cooperative cancellation.

---

## 4. Resource & Security Controls

| Resource | Boundary / Ceiling | Mechanism |
|---|---|---|
| Max File Size | 250 MiB | Checked at conversion entry point (`convert_request`) |
| Max Pages | 2000 pages | Enforced in `NativePdfTextExtractor`, `PdfToDocxReconstructor`, `PdfWorkbench` |
| Max Dimensions | 14,400 points | Verified in `PdfPageRenderer` |
| Max Raster Pixels | 16,000,000 pixels | Downscaled in `PdfPageRenderer` / Clamped in `ImageToPdfConverter` |
| DOCX Integrity | Magic bytes + zip integrity | Validated PK header + `word/document.xml` existence |
| Rendering Timeout | 5 to 300 seconds (default 60s) | Subprocess polling with process kill on expiry |
| Memory Limits | CPU inference | ONNX Runtime CPU provider; no GPU allocations |
| Cancellation | Cooperative | Polled between pages, before OCR, during workbench ops & rendering subprocess |
| Output Atomicity | Atomic rename | Written to temporary file and renamed atomically |

---

## 5. Application Settings & Global Destination Service (`AppSettings`)

Implemented in `src/localshift/settings.py` via `QSettings("LocalShift", "LocalShift")`.

### Core Capabilities:
- **Persistence:** Retains preferences across application restarts, including:
  - `save_to_folder_enabled` (bool, default: `False`)
  - `save_to_folder_path` (str, default: `""` or user desktop)
  - `theme` (str, default: `"dark"`)
  - `radial_gesture_enabled` (bool, default: `True`)
- **Directory Validation (`validate_destination_directory`):**
  - Verifies path existence and directory attribute.
  - Performs active write-accessibility probe by creating, writing, and unlinking a temporary sentinel file (`.localshift_write_test_*`). Detects read-only permissions, disconnected network shares, and ejected removable volumes.
- **Unified Resolution Policy (`resolve_destination`):**
  A single, deterministic hierarchy applied across all GUI tabs, radial conversions, and batch conversions:
  1. **Explicit Per-Job Destination:** User-specified output path or folder passed directly to the operation.
  2. **Global Custom Destination:** Used if `save_to_folder_enabled` is active and the directory is valid and writable.
  3. **Workflow Fallback:** The source file's parent directory or standard workflow default.

---

## 6. Windows Drag-and-Drop & Radial Conversion Gesture Architecture

### Windows OLE Drag Lifecycle & Boundary Realities
A standard Windows desktop application cannot intercept or monitor external File Explorer mouse drag operations when the cursor is outside application window boundaries without intrusive global hooks or privileged DLL injection.

LocalShift implements a native, supported OLE drop target integration:
- **Active Drop Target (`setAcceptDrops(True)`):** `MainWindow`, `FileConverterTab`, and `RadialConversionMenu` all register as standard Windows OLE drop targets.
- **Root Cause & In-Window Overlay Architecture:**
  - *Root Cause of Gesture Failure:* In Windows OLE, spawning a new top-level popup window (`Qt.WindowType.Tool` or `Qt.WindowType.WindowStaysOnTopHint`) during an active OLE drag sequence causes Windows OLE to drop capture or fail `IDropTarget` routing between different top-level HWNDs.
  - *In-Window Overlay Solution:* `RadialConversionMenu` supports `is_overlay=True`, rendering the radial dial and dimmed backdrop directly as a child widget within `MainWindow`. `MainWindow` remains the single, persistent `IDropTarget` HWND registered with Windows OLE, ensuring that `dragEnterEvent`, `dragMoveEvent`, and `dropEvent` never lose capture or trigger window activation changes.
- **Physical Shift Key State Detection (`is_shift_pressed()`):**
  - Uses Win32 `GetAsyncKeyState(VK_SHIFT = 0x10) & 0x8000` with fallback to `QGuiApplication.keyboardModifiers()`.
  - Accurately detects whether Shift is held even when Qt's event modifier bitmask is temporarily omitted during high-velocity external drags across window boundaries.
- **In-Flight Petal Hover & Drop:**
  - `MainWindow` forwards coordinates to `radial_overlay.track_drag_pos(pos)`.
  - Circular petal hit-testing (`petal_at_pos(pos)`) highlights the hovered format petal with radial outward offset and indigo hover glow.
  - Releasing/dropping directly onto a format petal triggers conversion immediately (`auto_start=True`) without requiring secondary confirmation modals.
- **Safety, Cancellation & Fallbacks:**
  - Pressing `Escape`, dropping on empty backdrop, or dragging out of window boundaries immediately dismisses the overlay cleanly without triggering unwanted conversions or leaving orphaned state.
  - Keyboard accelerator fallback: Shift + Space invokes the radial dial with Arrow key navigation and Enter confirmation.
  - Explicit UI fallbacks: "Open Radial Menu" buttons in header and drop cards, plus standard queue conversion controls.

### Background Shift+Drag & Explorer Selection Architecture (Milestone 16C)
To achieve the Tangerine-style background desktop experience without installing invasive global keyboard hooks or injecting DLLs into Windows Explorer:
- **`BackgroundGestureController` (Non-Invasive Polling):**
  - Runs a lightweight 60ms timer polling physical mouse drag state (`GetAsyncKeyState(VK_LBUTTON = 0x01)`) and Shift modifier (`is_shift_pressed()`).
  - Checks if the active foreground window is Windows File Explorer or the Desktop (`is_explorer_or_desktop_foreground()`), matching HWND classes: `CabinetWClass`, `ExplorerWClass`, `Progman`, and `WorkerW`.
  - When a drag gesture (movement > 8px) with Shift held is detected in Explorer:
    - Queries active Explorer window selection via Windows COM interface `Shell.Application` (`IShellWindows`).
    - Obtains full resolved filesystem paths for all selected items in real-time (~90ms execution).
    - Summons the floating `RadialConversionMenu` centered directly at cursor position (`is_overlay=False`).
    - Continuously updates hovered petals via `mapFromGlobal()` and `track_drag_pos()`.
    - On mouse button release, detects if cursor is over a valid format petal and executes immediate conversion to the configured Save to Folder destination.
- **Start with Windows & System Tray Operation:**
  - Registers `HKCU\Software\Microsoft\Windows\CurrentVersion\Run\LocalShift` pointing to the executable with `--minimized` argument (per-user, zero administrator privileges required).
  - Runs quietly in system tray via `QSystemTrayIcon` with context menu actions ("Open LocalShift", "Shift + Drag Conversion Gesture", "Start with Windows", "Quit").
  - System tray completion toasts with `messageClicked` navigation revealing output in File Explorer.

## 7. Document Reconstruction & XML 1.0 Sanitization Architecture

### XML 1.0 Strict Compatibility Enforcement
`python-docx` serializes document content through `lxml.etree`. XML 1.0 strictly prohibits character codes in the ranges:
- `0x00–0x08` (including NULL byte `\x00`)
- `0x0B–0x0C` (vertical tab `\x0b`, form feed `\x0c`)
- `0x0E–0x1F` (ASCII control codes)

PDF text extraction from embedded fonts and OCR decoders frequently outputs vertical tabs, form feeds, and NULL bytes.
- **Centralized `sanitize_xml_text(text: str) -> tuple[str, int]`:**
  - Regex `_XML_INVALID_CHAR_RE = re.compile(r"[\x00-\x08\x0e-\x1f\x7f-\x84\x86-\x9f\ud800-\udfff\ufffe\uffff]")`
  - Replaces `\x0c` (form feed) and `\x0b` (vertical tab) with standard newlines `\n`.
  - Strips all illegal control characters while preserving valid whitespace (`\t`, `\n`, `\r`), international Unicode (Latin, Cyrillic, Greek, Arabic, Devanagari, CJK), and emojis.
  - Sanitization is applied unconditionally to paragraph text, run text, heading text, bullet points, OCR text blocks, and table cell contents.
- **Atomic File Replacement:**
  - DOCX generation saves first to `.tmp_<filename>.docx` and performs atomic rename via `Path.replace()`, preventing corrupt partial files if process terminates or encounters errors.

---

## 8. Milestone 16D: Gesture Stability, Multi-Source Drag Architecture & Color-Accurate PDF Rendering Pipeline

### A. Non-Focus-Stealing Radial Overlay & Boundary Hysteresis
To resolve radial menu jitter, cursor feedback loops, and broken drag capture:
- **Focus Preservation via Native Window Flags:**
  - Floating radial menu is initialized with `Qt.WindowType.WindowDoesNotAcceptFocus | Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint`.
  - Sets `Qt.WidgetAttribute.WA_ShowWithoutActivating` and `FocusPolicy.NoFocus`.
  - `show_at_cursor()` anchors geometry without calling `activateWindow()` or `setFocus()`, completely preventing Windows from revoking mouse capture from the drag source (File Explorer, Desktop).
  - Removes premature window destruction in `ActivationChange` event handlers.
- **Stable Polar Sector Hit-Testing with Hysteresis:**
  - De-couples rendering geometry from collision testing.
  - Computes exact polar sector: $\text{angle} = \operatorname{atan2}(-(y - cy), x - cx)$, mapped clockwise from 12 o'clock.
  - Implements a $\pm 6^\circ$ sticky angular deadband and circular disc proximity check. When the cursor hovers on the boundary between adjacent petals, the currently hovered petal remains active until the cursor crosses the deadband, eliminating boundary oscillation and visual flickering.
  - Only triggers Qt widget repainting (`self.update()`) when `_hover_index` actually changes, preventing redundant painting cycles during continuous pointer movement.

### B. Discrete Gesture State Machine & Drag Source Adapter Hierarchy
The gesture lifecycle is strictly governed by `GestureStateMachine` with explicit transitions:
- `IDLE` -> `DRAG_CANDIDATE` -> `MENU_VISIBLE` -> `TARGET_SELECTED` -> `CONVERTING` -> `COMPLETED` / `FAILED` / `CANCELLED`.
- Instant cancellation on `VK_ESCAPE` (`0x1B`) and clean dismissal when the user releases the Shift modifier before dropping, allowing native Windows drag-and-drop operations to proceed unhindered.
- Source Adapter architecture (`DragSourceAdapter`):
  - `ExplorerDragSourceAdapter`: Windows File Explorer (`CabinetWClass`, `ExplorerWClass`) via COM `IShellWindows`.
  - `DesktopDragSourceAdapter`: Windows Desktop (`Progman`, `WorkerW`).
  - `OleDropSourceAdapter`: Direct OLE drag-and-drop into LocalShift UI (`QDragEnterEvent` / `urls`).
  - `FallbackSourceAdapter`: Explicitly identifies virtual drag items (browsers, archive viewers) lacking filesystem paths and provides user guidance.

### C. Color-Accurate PDF Rendering & Color Pipeline
- **Byte Order Rectification (`pypdfium2`):**
  - Native PDFium renders bitmaps in BGR byte order (`[B, G, R]`) by default.
  - `PdfPageRenderer.render_page()` enforces `rev_byteorder=True`, ensuring native RGB/RGBA byte alignment and eliminating Red/Blue channel swapping.
  - Added `PdfPageRenderer.render_page_to_image()` using native C-level `bmp.to_pil().copy()` for row-stride and transparent background compositing.
  - Lossless PNG encoding preserves exact vector and raster color patches.
  - Background-composited JPEG rendering applies user-defined background color without introducing color shifts.
  - Validated with automated visual color test suite (`tests/test_pdf_color_fidelity.py`) with Mean Absolute Error (MAE) < 3.0 across pure RGB primaries, neutral grays, and the Team Lemon sample corpus.
