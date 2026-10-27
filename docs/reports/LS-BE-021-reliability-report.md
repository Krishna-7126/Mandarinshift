# LocalShift Milestone 21 — Global Gesture Reliability, Physical Verification & Production Readiness

**Date:** 2026-10-27  
**Status:** Reliability fixes implemented and automated tests pass; physical compatibility and release performance gates remain open  
**Python environment:** Project `.venv`, Python 3.11.9, RapidOCR 1.2.13  

## Audit findings and fixes

| Verified issue | Evidence and impact | Change |
|---|---|---|
| Radial dispatch converted the whole existing queue | `apply_radial_format()` changed only dropped rows, then called `start_conversion()` which iterated every queued file. Existing unrelated files could be converted. | Radial dispatch passes the exact validated dropped path set; ordinary queue conversion still processes the full queue. Duplicate paths in one payload are scheduled once. |
| Hover state could remain lit after leaving sectors | `dragMoveEvent()` only changed hover for nonnegative sector hits, leaving the prior petal visually selected in the hub/dead zone. | Every move updates to the hit sector or clears to `-1`; existing hysteresis and repaint-on-change remain. |
| Active OLE drag could be closed by the fixed fallback timer | Release armed a 500 ms timeout regardless of an accepted OLE drag, risking closure before a delayed `dropEvent`. | The target tracks accepted OLE drag activity. Release does not arm the timeout during an active drag; timeout defers while OLE is active or the mouse remains down. Drag-leave and rejected drops restart safe cleanup. The 500 ms fallback remains for no-payload cases; physical timing still needs verification. |
| Duplicate/stale signal could dispatch more than once | `_on_format_selected()` had no active-menu/state check. | Dispatch is accepted only from the current `MENU_VISIBLE` gesture; subsequent or stale signals are ignored. |
| Gesture controller was never notified when conversion finished | Completion/failure methods existed but the conversion worker completion callback did not call them, leaving state stuck at `CONVERTING`. | Batch completion now reports success/failure, resets gesture state and drag resources, and permits a later gesture. |
| Gesture could start a second worker during an active conversion | Radial selection could overwrite the stored `QThread` while its current worker was running. | Radial and ordinary conversion entry points reject overlapping work with a clear message; dropped paths are not added before this rejection. |
| Closing while global monitoring was off could still hide the app to tray | `closeEvent()` checked only for a visible tray icon, even though its documented behavior was to hide only when monitoring. | OFF now exits cleanly; ON hides only when a visible tray icon is available. |
| Persisted string `"false"` could be interpreted as enabled | Boolean conversion of a nonempty QSettings string is true. | Stored strings use the same explicit true-value parsing as other persisted booleans; false remains off across restart. |
| Diagnostics could disclose the startup executable path | Startup-registration logging included the full executable path. | Startup log now reports the action without logging the path. |
| Manual checklist had no structured evidence record | Physical cases could not be distinguished from untested work in a machine-readable report. | Interactive diagnostics write a JSON report before launch, leave every physical case `NOT TESTED`, and update only from explicit operator responses. |

No selection-query fallback, OS hook, DLL injection, or file execution was added.

## Current explicit gesture lifecycle

`IDLE -> DRAG_CANDIDATE -> MENU_VISIBLE -> TARGET_SELECTED -> CONVERTING -> COMPLETED|FAILED -> IDLE`

Escape, Shift release, monitoring OFF, invalid payload, drop outside a sector, timeout, and shutdown clear gesture state without dispatch. Only the current menu's validated local-file OLE payload can dispatch, and the payload alone determines the conversion jobs. The 500 ms no-payload timeout is now event-aware but still requires real source timing validation.

## Automated verification

| Command | Result |
|---|---|
| `.\scripts\run_tests.ps1` | **711 passed, 3 skipped, 0 failed** in 158.45 s |
| Full-suite skips | Three symlink tests require Windows Developer Mode/admin permissions or `LOCALSHIFT_TEST_SYMLINKS=1` |
| Word/Excel backend integration | Word COM and Excel COM were available during the final full run; their integration tests ran. LibreOffice was not detected. |
| Focused gesture/settings/GUI/report suite | **90 passed** |
| `tests\test_pdf_color_fidelity.py` | **6 passed** |
| `tests\test_all_conversion_routes.py` | **54 passed** |
| `tests\test_packaging.py` | **6 passed** |
| `scripts\verify_windows_gesture.py --check` | All automated route/destination checks passed |
| `python -m compileall -q src tests scripts` | Passed |
| `git diff --check` | Passed |

The initial full run had one failure because Excel/LibreOffice was unavailable at that time. The production code correctly reports that requirement. The test now skips only when neither backend exists and retains its output assertions when a backend is available. During the final run, Office COM was available and the test passed.

## Local conversion measurements — not a production performance qualification

These were one-pass local fixture conversions using temporary output directories; source hashes were unchanged. Times are measured execution latency, not statistically significant throughput. `tracemalloc` reports Python heap only and excludes PDFium, ONNX Runtime, and other native allocations.

**Conditions:** Windows 11 Home Single Language, build 26300; AMD Ryzen 7 7435HS; 15.7 GiB RAM; Python 3.11.9; PySide6 6.12.0; RapidOCR 1.2.13; ONNX Runtime 1.31.0.

| Workload | Input | Elapsed | Peak traced Python heap | Source unchanged |
|---|---:|---:|---:|---|
| Multipage digital PDF → DOCX | 3 pages, 1,338 B | 82.95 ms | 2.32 MiB | Yes |
| Dense digital PDF → DOCX | 1 page, 1,082 B | 49.96 ms | 2.27 MiB | Yes |
| Holdout bylaws PDF → DOCX | 10 pages, 10,809 B | 326.43 ms | 2.32 MiB | Yes |
| Scanned PDF → DOCX, forced OCR | 1 page, 14,133 B | 2,668.78 ms | 158.68 MiB | Yes |

The first two fixtures are small and are included as smoke measurements, not large-document benchmarks. No repeated runs, batch-throughput measurement, native peak working-set measurement, conversion-output visual audit, gesture response latency, drop-to-worker-start latency, enabled-polling CPU overhead, disabled-app idle CPU usage, or repeated-gesture memory trend was recorded. The disabled setting is automated-tested to keep its poll timer inactive. A live global polling benchmark was not started to avoid capturing or interrupting the operator's desktop.

## Physical compatibility matrix

The initial machine-readable matrix is [LS-BE-021-physical-verification.json](./LS-BE-021-physical-verification.json). It intentionally contains no PASS results.

| Source / scenario | Application/version | Payload received | Selected files/output/cancellation | Result |
|---|---|---|---|---|
| Explorer, one supported file | Windows File Explorer; Windows build 10.0.26300 | Not observed | Not observed | **NOT TESTED** |
| Explorer, multiple supported files | Windows File Explorer; Windows build 10.0.26300 | Not observed | Not observed | **NOT TESTED** |
| Desktop, one supported file | Windows Desktop; Windows build 10.0.26300 | Not observed | Not observed | **NOT TESTED** |
| Desktop, multiple supported files | Windows Desktop; Windows build 10.0.26300 | Not observed | Not observed | **NOT TESTED** |
| Third-party file manager | None recorded | Not observed | Not observed | **NOT TESTED** |
| Unsupported/virtual source | No source recorded | Not observed | Not observed | **NOT TESTED** |
| Mixed-DPI monitors | Monitor inventory not recorded | Not applicable | Cursor alignment not observed | **NOT TESTED** |
| Escape/Shift release/cancellation | Physical interaction not run | Not applicable | Output cancellation not observed | **NOT TESTED** |
| Monitoring toggle/restart | Physical restart interaction not run | Not applicable | Persistence interaction not observed | **NOT TESTED** |
| Unsupported format/size/collision/source immutability | Physical interaction not run | Not applicable | Not observed | **NOT TESTED** |

Automated Qt payload tests are not evidence of cross-application OLE delivery. Do not claim compatibility for Explorer, Desktop, or a third-party manager before recording its real application/version and observed results.

## Commands for operator verification

From the repository root:

```powershell
.\.venv\Scripts\python.exe scripts\verify_windows_gesture.py --interactive --log-file .\gesture-diagnostics.log --report-file .\docs\reports\LS-BE-021-physical-verification.json
```

Enable the feature explicitly in Settings for global tests. The report starts with every case `NOT TESTED`; after closing the app, enter only observed outcomes. Do not enter file names or paths in notes. Test the two Explorer scenarios separately, Desktop, a third-party manager if installed, a virtual/remote source, mixed DPI if available, cancellation, and OFF/ON plus restart persistence. Compare file counts and output correctness without writing private names into the report.

## Release gate and limitations

- **Implemented:** exact payload-only dispatch, stale-hover clearing, OLE-aware timeout, duplicate guard, completion/failure cleanup, exact queue scoping, overlap guard, opt-in persistence, off-state shutdown, structured manual reporting.
- **Automated verified:** results in the table above.
- **Manually verified:** none of the physical source cases.
- **Not tested:** real Explorer/Desktop/third-party drag, mixed DPI, full output correctness/source immutability via external drag, live gesture/idle performance, and release packaging build.
- **Limitations:** External sources must provide local file URLs to Qt. Virtual/remote items are rejected. A payload that never reaches the target safely times out. Support is not universal or certified. Full native memory use is not measured by the Python heap benchmark.

**Next action:** Run the interactive command above on the Windows desktop, explicitly enable global conversion, and record actual results in the JSON. Revisit the source compatibility and performance gates only after that evidence exists. No commit or push was made.
