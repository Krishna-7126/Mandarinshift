# LocalShift Milestone 20A — Repository Audit and Baseline

**Date:** 2026-10-26  
**Base commit:** `965c013` (`feat(pdf-suite): implement 32-tool offline PDF productivity suite and Windows shell integration (v0.19.0)`)  
**Initial worktree:** Clean (`main`)  
**Audit status:** Complete; baseline regression repaired and full suite green

## Executive summary

The repository already contains the majority of the conversion, PDF-suite, gesture, settings, CLI, and desktop foundations described in Milestone 20. This audit did not replace those systems. It confirmed 54 registered directional conversion routes, four adapters, and 34 PDF-suite registry entries (32 `READY`, 2 `CONFIG_REQUIRED`). Thus “54 routes” and “32 ready PDF tools” are different counts; the earlier report's title “32-Tool” omitted the two registered configuration-required tools.

The initial full test run collected 689 tests and found **675 passed, 13 skipped, 1 failed**. The failure exposed a real planner bug: an unavailable DOCX→PDF adapter suppressed option validation, allowing an invalid renderer setting to go undiagnosed when Word/LibreOffice was absent. The planner now validates options declared by the registered adapter even when that adapter is unavailable. The targeted regression and full suite then passed: **687 passed, 3 skipped, 0 failed**. The three skips are the Windows symlink-permission tests.

The working tree was clean before this audit. Test execution modified three tracked unseen-document PDF fixtures; after verifying their initial clean status, those test-generated mutations were restored. No user changes were discarded.

## Baseline and verification

| Check | Result |
|---|---|
| Initial full suite | 675 passed, 13 skipped, 1 failed (689 collected) |
| Failure | `tests/test_docx_pdf.py::TestDocxPreflightAndPlanning::test_preflight_invalid_option_value` |
| Focused regression after fix | Passed |
| Full suite after fix | **687 passed, 3 skipped, 0 failed** in 156.75 s |
| Conversion-route suite collection | 55 tests |
| PDF-tool suite collection | 25 tests |
| Registered routes | **54** |
| PDF suite entries | **34**: 32 READY, 2 CONFIG_REQUIRED |
| Python used | 3.14.3 |
| Runtime versions | Pillow 13.0.0; pypdfium2 5.14.0; PySide6 6.12.0; python-docx 1.2.0; ONNX Runtime 1.26.0; RapidOCR 1.2.3 |
| Available DOCX→PDF backend | Microsoft Word COM (`word_com`) |

The project venv is Python 3.11 and initially lacked pytest and the runtime dependencies. I added pytest and wheel to that venv while attempting the declared editable install; dependency downloads did not complete, so the suite was run with the preinstalled Python 3.14.3 environment and its runtime/test packages. No project dependency manifest was changed.

### Baseline fix

`validate_preflight()` only obtained a route's option specifications in the branch where the route was available. The unavailable-adapter branch therefore missed validation of supplied options. It now obtains those specifications whenever an adapter is registered, independently of current backend availability. This preserves the actionable `ADAPTER_UNAVAILABLE` finding and also reports invalid option values.

## Conversion support matrix

Every route is registered through one of these adapters. The listed checks correspond to the existing exhaustive route suite (`tests/test_all_conversion_routes.py`, 55 tests); availability is dynamically queried where specified.

| Directional family | Routes | Adapter / engine | Runtime dependency / backend | License notes | Availability and coverage |
|---|---:|---|---|---|---|
| Raster → raster (all distinct pairs among BMP, GIF, ICO, JPEG, PNG, TIFF, WebP) | 42 | `PillowImageAdapter` / Pillow | Pillow | Pillow license (HPND / permissive) | READY; 55-test route suite includes the 54-route integration coverage |
| Raster → PDF (BMP, GIF, ICO, JPEG, PNG, TIFF, WebP) | 7 | `ImageToPdfAdapter` / `ImageToPdfConverter` | Pillow; pypdfium2 used in document operations, not raster-to-PDF encoding | Pillow license; pypdfium2 Apache-2.0/BSD-3-Clause where used | READY; covered by route and image-to-PDF tests |
| PDF → TXT | 1 | `PdfDocumentAdapter` / text extraction and local OCR | pypdfium2; RapidOCR + ONNX Runtime for OCR | PDFium/pypdfium2 Apache-2.0/BSD-3-Clause; RapidOCR Apache-2.0; ONNX Runtime MIT | READY; covered by PDF extraction and route tests |
| PDF → DOCX | 1 | `PdfDocumentAdapter` / `PdfToDocxReconstructor` | pypdfium2; python-docx; local OCR for scans | PDFium/pypdfium2 Apache-2.0/BSD-3-Clause; python-docx MIT | READY; reconstruction tests; fidelity remains heuristic |
| PDF → PNG/JPEG | 2 | `PdfDocumentAdapter` / `PdfToImageExporter` | pypdfium2/PDFium; Pillow | PDFium/pypdfium2 Apache-2.0/BSD-3-Clause; Pillow permissive | READY; PDF image export and route tests |
| DOCX → PDF | 1 | `DocxToPdfAdapter` / `DocxToPdfRenderer` | Microsoft Word COM or LibreOffice; backend dynamically detected | Word proprietary; LibreOffice MPL-2.0; python-docx MIT | READY when a local renderer exists; dynamic availability, DOCX/PDF tests |
| **Total** | **54** | **4 adapters** | Offline local processing | No runtime download or network conversion path identified | Count measured directly from `default_registry.supported_routes()` |

PDF productivity tools are operations, not conversion-registry routes. For example, PDF merge/split/reorder retain PDF as the format, and PDF→PDF/A is a specialized tool. Do not add these to the 54 directional conversion-route count.

## PDF tool registry reconciliation

Measured `PdfToolRegistry.get_all_tools()` contains **34 entries**: 32 `READY` and 2 `CONFIG_REQUIRED` (`protect_pdf`, `translate_pdf`). Existing test coverage includes 25 PDF-tool tests. Several tools have implementations but their current visible descriptions or claimed guarantees need correction:

| Tool / claim | Implementation observed | Audit conclusion |
|---|---|---|
| PDF→XLSX | Extracted text split on tabs / repeated spaces into inline-string cells; no formulas, workbook semantics, or general layout reconstruction | Useful text/table-like extraction, not spreadsheet conversion with preserved formulas/layout; keep limitations explicit |
| PDF→PPTX | Each page rasterized to PNG and packaged as a slide image, either via COM or OpenXML | Slides contain page images and are not editable source-document text/shapes. Overlaying new elements does not make the source content editable |
| PDF/A | Word COM export path plus fallback that appends `pdfaid` text to the end of PDF bytes | Fallback is not a valid PDF/A conversion or conformance proof. Metadata markers do not establish ISO 19005 compliance |
| “Digital signature” | Rasterized PDF pages stamped with signer/date/hash text | This is a visual seal, not a cryptographic PDF digital signature; hashing the source does not authenticate the output |
| Redaction | Searches text, rasterizes every page, paints black boxes at matches | Rasterization removes selectable source text, but this is not vector-preserving redaction; no explicit “no matches” refusal is present in the inspected flow |
| Tool total | Registry contains 34 definitions | The “32 tools” label counts READY entries, not all entries; document both counts and status |

The earlier Milestone 19 report's claims of strict PDF/A compliance and fully editable PDF-to-PowerPoint output are not supported by the inspected fallback implementations. Do not repeat these as verified capabilities. Any digital-seal UI must not imply cryptographic signature validation.

## Gesture and settings baseline

- `AppSettings` persists `radial_gesture_enabled`; before Phase 1 it defaulted to `True`.
- `MainWindow` constructs `BackgroundGestureController` unconditionally and starts monitoring when that preference is true.
- The controller polls Windows mouse, Shift, and Escape state; the tray also has a toggle. The app-scoped Qt event filter and in-window radial drop target are separate interaction surfaces.
- Explorer/Desktop adapters retrieve selected filesystem paths through Shell COM, not from Shift state. Non-Explorer sources are not proven compatible by this integration.
- The existing Settings dialog has Save to Folder, theme, gesture and startup controls, but its gesture explanation describes broad Shift/drag behavior and has no explicit supported-source guidance or test-gesture button.
- Both the Settings and tray toggles already start/stop the background controller. Phase 1 retains that behavior and clarifies its status and supported sources.

No real Windows Explorer interaction was performed in this audit. Simulated Qt tests are not evidence of cross-application OLE behavior.

## Destination and offline behavior

`AppSettings.resolve_destination()` documents the precedence explicit destination → enabled global Save to Folder → workflow fallback. The PDF Suite UI passes its selected/global destination into the tool engines. CLI conversion commands expose explicit output-directory arguments. This audit did not exercise each workflow's destination resolution or collision/cleanup behavior end-to-end; those remain Phase 4 verification work.

The existing README and architecture describe offline operation and bounds, but milestone-specific tests are still required for new SVG, archive, audio, and video decoders before claiming those families. No network fallback was found in the route registry inspected for this report.

## Phase 0 files changed

- `src/localshift/planner.py`: keep option validation active for registered-but-unavailable adapters.
- `docs/reports/LS-BE-020A-audit-report.md`: this audit and the measured baseline.

## Remaining phases / blockers

Phase 0 is complete and the post-fix regression suite is green. Phase 1 can begin. Items that must remain explicitly unverified until their phase is completed:

- Native Explorer/Desktop gesture behavior on real Windows sources and per-source compatibility.
- SVG security and rendering policies; DOCX/XLSX/PPTX conversion fidelity beyond existing routes.
- Safe ZIP creation/extraction and adversarial archive limits.
- FFmpeg capability, licensing, cancellation and resource behavior; video support is not implemented by this audit.
- Consistent Save to Folder behavior across every workflow and CLI precedence.
- UI screenshots, design review, release packaging, and reproducible performance benchmarks for Milestone 20.

## Milestone 20 continuation: restored environment and final status

The measurements above are the audit-time baseline, not the final Milestone 20 result. The project venv was subsequently restored with Python 3.11.9 and declared development/desktop dependencies. The first full run there found **681 passed, 3 skipped, 9 failed**: RapidOCR 1.4.4 was incompatible with the repository's expected OCR API/model and quality assertions, and two test assumptions were incompatible with Python 3.11. `pyproject.toml` now bounds RapidOCR to `>=1.2.3,<1.3`; the test doubles were adjusted for Python 3.11.

The active global gesture no longer uses Explorer selection querying. It requires a validated local-file OLE payload and a drop on a format sector. Final `.\scripts\run_tests.ps1` result: **694 passed, 3 skipped, 0 failed** in 169.34 seconds; the three skips require symlink privileges/Developer Mode. `scripts/verify_windows_gesture.py --check` and `compileall` also passed. See [LS-BE-020B-gesture-report.md](./LS-BE-020B-gesture-report.md) for commands, changes, and the source-by-source compatibility matrix.

Actual Explorer, Desktop, third-party manager, mixed-DPI, conversion-output, and source-immutability interactions were not run. Milestone 20's physical verification gate remains open; no global source support is certified.
