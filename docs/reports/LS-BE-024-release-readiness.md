# LocalShift Milestone 24 — Release Readiness & Windows Verification

**Assessment date:** 2026-10-28  
**Decision:** **BLOCKED — partially verified; do not call this source release-ready.**

## Executive summary

- Fresh full suite: **752 passed, 3 skipped, 0 failed** in 165.91 seconds.
- Focused PDF-to-DOCX and unseen-document suites: **36 passed, 0 skipped, 0 failed**.
- The three protected unseen PDF fixture hashes match the baseline before and after test runs.
- A clean Python 3.11.9 environment installed documented extras and built a portable bundle and Inno Setup installer in isolated temporary directories. Bundle resources, CLI help, GUI startup, and synthetic image conversion were checked.
- Supplied gesture diagnostics show local payload previews and one DOCX conversion reaching COMPLETED, but lack source-app/case attribution, output validation, and source hash. Physical results remain **0 passed, 0 failed, 10 NOT TESTED**.
- Physical drag compatibility, mixed-DPI behavior, assistive technology, and installer lifecycle remain unverified.

The original inspection snapshot is in [LS-BE-024-baseline.md](./LS-BE-024-baseline.md). Prior findings are in [LS-BE-023-release-readiness.md](./LS-BE-023-release-readiness.md).

## Baseline and preservation

The initial six Milestone 23 changes and subsequent Milestone 24 work were preserved. Nothing was reset, cleaned, staged, committed, pushed, or published. Existing build/dist outputs were not touched. Temporary build outputs are under %TEMP%\LocalShift-M24-final-verified.

| Protected fixture | SHA-256 |
|---|---|
| val_02_scanned_receipt.pdf | C039B5FC1B95D0CB0B946BB4350EEE44B9E7CB08189D48796AA397AB7F0373BD |
| val_03_mixed_report.pdf | 53557216A55351F2C98C62EEB711C76231494F20F1B4C39E55C7A1AC8E5EC662 |
| val_09_technical_manual_figures.pdf | CF3B51E874594C9BE9534603FE6FD4BC7BFA1787EF93C098F13DE33BC1F61852 |

## Verified fixes

1. The unseen-validation fixture setup now requires existing PDFs and fails if any are missing; it does not rewrite fixtures.
2. Standard packaging requires fresh, non-overlapping output/work directories and refuses existing paths instead of deleting previous artifacts. The legacy destructive --clean-only option was not used.
3. The RapidOCR hidden import now points to the module present in the tested 1.2.13 package.
4. PyInstaller 6.22.3 is declared as an optional build dependency. Installer source/output directories are configurable.
5. No new physical gesture runtime defect was established. Existing radial screen-edge work and tests were retained; physical OLE routing remains unproven.

## Operator evidence review

The supplied physical JSON records Windows build 10.0.26300 and Python 3.11.9, but all ten cases remain NOT TESTED. Its 195-line gesture log records 17 OLE preview events, one accepted one-file DOCX drop followed by CONVERTING → COMPLETED → IDLE, and six CANCELLED transitions. It has no source application, case ID, output check, or source hash, so it certifies no compatibility scenario.

The v2 harness runs one selected case per GUI session and writes allowlisted, case-tagged diagnostics. It catches the GUI's successful SystemExit(0), allowing post-session collection. Supplied v1 JSON and text log were left unchanged; no interaction was performed with the v2 harness.

The reported “Input file not found” event is not present in the supplied log and was not reproduced. Conversion validates source existence; OLE paths are validated on preview and drop. Reproduce the issue under RELIABILITY before changing conversion behavior.

## Automated verification

| Check | Result |
|---|---|
| Fresh full suite | .\scripts\run_tests.ps1 — **752 passed, 3 skipped, 0 failed** in 165.91 seconds (2026-10-28). |
| Earlier full suite | 751 passed, 3 skipped, 0 failed in 183.67 seconds; superseded. |
| Skips | Two symlink cases in tests/test_converter.py and one in tests/test_reliability.py; Windows Developer Mode/elevation required. |
| Focused DOCX suites | pytest tests/test_pdf_docx.py tests/test_unseen_validation.py -rA -q — **36 passed, 0 skipped, 0 failed**. |
| Gesture harness tests | 21 passed. |
| Gesture automated self-check | Passed; does not exercise physical OLE behavior. |
| Packaging/OCR focused checks | 12 passed in clean venv; final packaging-only rerun passed 8 tests. |
| Compile/static checks | compileall and git diff --check passed. |

Automated coverage includes conversion routes, source immutability, collisions, PDF fidelity, radial geometry, payload validation, cancellation, and packaging. It does not prove external Windows drag behavior.

## Current-source build verification

Environment: Windows build 10.0.26300, Python 3.11.9, PyInstaller 6.22.3, hooks-contrib 2026.9, Inno Setup 6.7.3. A fresh venv installed .[dev,desktop,build]. The build used fresh temporary output/work paths.

Verified: GUI/CLI executables, pdfium.dll, ONNX Runtime DLLs, and OCR models were present; --verify-only and CLI --help passed; minimized GUI remained alive for five seconds; bundled CLI converted a synthetic PNG to JPEG without changing the source hash. Inno Setup compiled, but installer execution was not tested.

| Temporary artifact | Size | SHA-256 |
|---|---:|---|
| LocalShift-Setup-0.14.0.exe | 98,584,392 bytes | 6d99759dd870874cbe4845cd346bef39860ae243adf547ae2205a3bc6c1ba7c0 |
| LocalShift.exe | 6,018,449 bytes | 59f66f220f101a9fb0628f6bb26175b0aa421795ba97f629544705a522b487dd |
| localshift-cli.exe | 6,023,830 bytes | 48adb27980c82dfb29043502c61f75e0410a37c65dff9bd8f491b94c236ed370 |

These are temporary verification artifacts, not official release artifacts. RELEASE_MANIFEST.md refers to prior artifacts. Package/installer metadata remains 0.14.0 while parts of documentation refer to 0.19.0-era work. Runtime dependencies are ranges, not a complete lock. Align release metadata before publication.

## Physical compatibility matrix

| Case | Observation required | Result |
|---|---|---|
| EXP-SINGLE | Explorer single file and correct output | **NOT TESTED** |
| EXP-MULTI | Explorer multi-file payload and exact output count | **NOT TESTED** |
| DESKTOP-SINGLE | Desktop single-file drag | **NOT TESTED** |
| DESKTOP-MULTI | Desktop multi-file drag | **NOT TESTED** |
| THIRD-PARTY | Identify manager/version; test single and multiple files | **NOT TESTED** |
| VIRTUAL | Unsupported/virtual payload safely rejected | **NOT TESTED** |
| MIXED-DPI | Monitor transitions at available scale factors | **NOT TESTED** |
| CANCEL | Escape, Shift/mouse release, cancellation cleanup | **NOT TESTED** |
| TOGGLE | OFF/ON and restart persistence | **NOT TESTED** |
| RELIABILITY | Unsupported/oversized input, collision, conversion failure, source hashes | **NOT TESTED** |

Keyboard-only, screen-reader, high-contrast, and touchpad behavior were not physically tested.

## Remaining blockers and next operator action

1. Run the case-attributed v2 checklist for all ten cases above. Keep unobserved cases NOT TESTED; record output correctness and source hashes.
2. On a disposable account or VM, install the built installer, launch it, convert a fixture, uninstall, and verify test outputs and user data.
3. Decide the release version and align package metadata, installer, changelog, and manifest.
4. Decide whether to add a complete Windows/Python dependency lock.

Release remains **BLOCKED** until physical compatibility evidence, installer lifecycle, and release metadata are resolved.
