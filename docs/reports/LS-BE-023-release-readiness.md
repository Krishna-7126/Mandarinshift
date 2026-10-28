# LocalShift Milestone 23 — Release Readiness & Regression Stabilization

## Release decision

**BLOCKED — do not describe the current source as release-ready.** The automated suite is green, but no physical drag-source, mixed-DPI, assistive-technology, or current-source packaging build was completed. These are release gates, not inferred passes.

## Findings and fixes

| Finding | Evidence and impact | Resolution |
|---|---|---|
| At screen edges, clamping could leave the global OLE target away from the activation pointer. | Offscreen reproduction at `(1, 1)` on an 800×800 screen positioned the 400×460 target at `(10, 10)`, mapping the pointer to `(-9, -9)` outside the target. At the opposite corner, the pointer mapped to `(409, 469)`, also outside. An external drag therefore could not reliably enter the window to deliver the file payload. | [radial_menu.py](../../src/localshift/radial_menu.py) now clamps the window while keeping the activation pointer inside its hit area. Tests cover each screen corner and synthetic negative-origin monitor coordinates. |
| "Start with Windows" failed for source checkouts. | The registry command directly executed `src/localshift/gui.py`; its relative imports fail outside package context with `ImportError: attempted relative import with no known parent package`. | [shell_integration.py](../../src/localshift/shell_integration.py) now launches `python -m localshift.gui --minimized`. A mocked registry regression test verifies the command. |
| Several workflow controls lacked explicit accessibility names. | The offscreen widget audit found unnamed tables, form fields, numeric editors, settings tabs, and controls, leaving assistive technology with ambiguous names. | [gui.py](../../src/localshift/gui.py) assigns names to the affected controls; [test_gui.py](../../tests/test_gui.py) asserts representative names. This is not a physical screen-reader test. |
| PDF-tool counts in user-facing documentation were stale. | The runtime registry reports 34 tools: 32 ready and 2 configuration-required. | Updated the README and test plan to state the registered and available counts separately. |
| README screenshots showed an older interface. | The prior screenshots did not match the current proof-sheet design and included missing-glyph rendering. | Added current offscreen dark/light converter, PDF catalog, and radial captures under `docs/screenshots/m23-*`; kept the previous image files. |
| Installer manifest size did not match the existing artifact. | Actual installer length is 97,877,415 bytes; the former entry was 97,875,968. Both artifact hashes match the manifest values. | Corrected the size entry in `docs/RELEASE_MANIFEST.md`. |

## Environment and automated verification

| Item | Result |
|---|---|
| Official command | `.\scripts\run_tests.ps1` |
| Result after radial edge correction | **730 passed, 3 skipped, 0 failed** in 177.03 seconds |
| Focused command | `.\.venv\Scripts\python.exe -m pytest tests\test_radial_menu.py tests\test_shell_integration.py -q -o addopts=''` |
| Focused result | **51 passed** in 1.94 seconds |
| Python / pytest | Python 3.11.9 / pytest 9.1.1 |
| Desktop / image / PDF / OCR packages | PySide6 6.12.0; Pillow 13.0.0; pypdfium2 5.14.0; RapidOCR 1.2.13; ONNX Runtime 1.31.0; python-docx 1.2.0 |
| Project requirement | Python `>=3.10`; the official launcher uses the project `.venv`, adds `src` to `PYTHONPATH`, and sets Qt to offscreen. |
| Skips | Three Windows symlink tests require Developer Mode or elevation. They are not passes. |
| Gesture diagnostics | `.venv\Scripts\python.exe scripts\verify_windows_gesture.py --check` — automated route and destination checks passed. This does not exercise a physical OLE drag. |
| Existing bundle verification | `.venv\Scripts\python.exe packaging\build.py --verify-only` — passed for the existing bundle's PDFium, ONNX Runtime DLL, and three OCR models. This is not a source rebuild. |
| Static checks | `.\.venv\Scripts\python.exe -m compileall -q src tests` and `git diff --check` — passed after the radial edge correction. |
| Conversion / PDF checks | The full suite includes route, source-immutability, output-collision, PDF color-fidelity, PDF tools, and packaging tests; all collected tests passed or were skipped as listed above. |

The existing installer is 97,877,415 bytes with SHA-256 `13469bf14d85e1d4d33a616b8b477c7654a5286449eeb25063c74fecdca92974`. The portable ZIP is 153,360,020 bytes with SHA-256 `de04a9b9f5000a05324760a2355703a06f4f50a15a8070ced464d92a630412d2`. Those checksums were recomputed and match the manifest. Neither artifact was rebuilt from the current source. A packaging build was not attempted because PyInstaller is unavailable in the project venv and the normal build path cleans existing `build` and `dist` outputs.

## UI and interaction evidence

- Current offscreen captures were reviewed for dark/light themes at 1020×680. The converter, PDF catalog, settings, and radial wheel are represented in the screenshots under `docs/screenshots/m23-*`.
- Offscreen layout probes at 760×560, 1020×680, and 1440×900 found the Recent panel hidden at minimum size, no queue horizontal overflow, and vertical (not horizontal) PDF-catalog scrolling. These results are Qt/offscreen checks, not physical display evidence.
- The screen-edge activation-pointer regression was reproduced before the fix and rechecked after: the pointer now maps inside the popup at both opposite corners. The helper also has deterministic cases for all corners and a virtual screen with negative origin. This verifies Qt geometry only, not Windows OLE routing or physical DPI transitions.
- The new accessible-name assertions passed in the full suite. No physical Narrator, NVDA, keyboard-only, or high-contrast assessment was performed.
- The physical display scaling and mixed-monitor coordinate behavior remain unverified. An offscreen image or synthetic pointer test cannot establish those behaviors.

## Global gesture compatibility matrix

The existing structured report at `docs/reports/LS-BE-021-physical-verification.json` still records **0 passed, 0 failed, 10 NOT TESTED**. No application in this table is certified as supported.

| Case | Source / scenario | Local payload, output, cancellation | Result |
|---|---|---|---|
| `EXP-SINGLE` | Windows File Explorer, one supported file | Not observed | **NOT TESTED** |
| `EXP-MULTI` | Windows File Explorer, multiple supported files | Not observed | **NOT TESTED** |
| `DESKTOP-SINGLE` | Windows Desktop, one supported file | Not observed | **NOT TESTED** |
| `DESKTOP-MULTI` | Windows Desktop, multiple supported files | Not observed | **NOT TESTED** |
| `THIRD-PARTY` | A third-party file manager, single and multiple files | Application/version and behavior not recorded | **NOT TESTED** |
| `VIRTUAL` | Browser, remote, archive, or virtual item | Safe rejection/fallback not physically observed | **NOT TESTED** |
| `MIXED-DPI` | Multiple monitors / available scaling factors | Not observed | **NOT TESTED** |
| `CANCEL` | Escape, Shift release, and cancellation | Physical cleanup not observed | **NOT TESTED** |
| `TOGGLE` | Monitoring OFF/ON and restart persistence | Physical setting/startup behavior not observed | **NOT TESTED** |
| `RELIABILITY` | Unsupported/oversized input, collision, source immutability | Physical end-to-end behavior not observed | **NOT TESTED** |

The diagnostic JSON records Windows build `10.0.26300` and Python 3.11.9, but all ten cases have null observations and empty evidence notes. Automated payload-validation tests establish code behavior for supplied test objects; they do not prove that Explorer, Desktop, or another application delivers that payload.

## Operator manual checklist

Record results in the structured verification JSON only after observing them. Use a disposable test directory with known, supported files. Record application/version, Windows build, monitor scaling, whether a genuine local-file payload arrived, file count, output correctness, cancellation result, and a short non-sensitive note. Do not record full paths, private filenames, or document contents.

1. **Default and opt-in:** Start LocalShift fresh. Verify global Shift+Drag is OFF. Enable it explicitly and verify the status indicator; turn it OFF again and verify ordinary in-app conversion still works.
2. **Explorer — single file:** Drag one supported local file, hover a format, and drop. Confirm the received file is the dragged file, the selected format matches the hovered sector at confirmation, the output opens correctly, and the original hash is unchanged.
3. **Explorer — multiple files:** Repeat with two distinct supported files. Confirm the payload contains exactly those files, both outputs are correct, and neither source changes.
4. **Desktop:** Repeat the single- and multi-file checks from the Desktop.
5. **Third-party manager:** If installed, record its exact product/version and repeat both cases. Otherwise leave the case NOT TESTED.
6. **Unsupported/virtual source:** Try a browser download/virtual item, remote item, or unsupported source. Confirm no selected-file substitution or conversion occurs and that the UI explains the fallback.
7. **Cancellation:** During an active drag, test Escape, Shift release, and source-side cancellation. Confirm the wheel closes, no output is produced, and the next gesture starts cleanly.
8. **Toggle/restart:** Disable the feature, restart LocalShift, and confirm monitoring stays OFF. Re-enable, restart, and verify only the saved explicit choice is honored.
9. **Display scaling and edges:** Repeat on each available monitor and while crossing monitor boundaries. Trigger near all four screen corners; confirm the pointer remains inside the wheel target and sectors remain reachable. Check sector hit-testing, text clipping, focus, and accidental activation.
10. **Failure and immutability:** With disposable copies, test unsupported format, oversized input, and an existing destination collision. Confirm a clear failure/fallback, no overwrite, and unchanged original hashes.
11. **Accessibility:** With a screen reader and keyboard-only input, inspect focus order, visible focus, labels, radial-menu navigation, and cancellation. Record the reader/version.

## Limitations and remaining release blockers

- Physical Explorer, Desktop, third-party file-manager, virtual-source, mixed-DPI, cancellation, and assistive-technology results remain **NOT TESTED**.
- Monitoring is designed to default OFF and requires an explicit user choice; automated settings tests passed. Physical startup/restart behavior remains unverified.
- Global conversion requires a trustworthy local-file drop payload. Unsupported or virtual payloads must be rejected or use the in-app file-open fallback; never substitute Explorer selection.
- No production performance measurements were taken for gesture tracking, disabled idle CPU, response latency, accepted-drop-to-conversion latency, throughput, large-document memory, or repeated-gesture cleanup.
- The existing distribution bundle passed integrity verification, but no current-source installer or portable package was built. Existing build outputs were left intact.
- This source has not been validated with a physical network monitor during this milestone; privacy claims are based on the documented local processing design and source review, not a captured network trace.
- **Test fixture side effect:** The unseen-validation generator rewrote `val_02_scanned_receipt.pdf`, `val_03_mixed_report.pdf`, and `val_09_technical_manual_figures.pdf` during the full suite. The operator chose to keep the generated versions. Preserve these current files; back them up before any future run that may regenerate fixtures.

## Next operator action

Run the numbered checklist above on the intended release machine, starting with Explorer single-file and multiple-file drops. Update the JSON only with observed results. Then obtain approval and a safe output location before building the current source, because the normal packaging command cleans existing `build` and `dist` directories. Do not release until the physical compatibility, accessibility, performance, and current-source packaging gates are either passed or explicitly removed from release scope.
