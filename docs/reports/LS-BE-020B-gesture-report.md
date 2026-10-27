# LocalShift Milestone 20B — Global Radial Gesture Controls and Compatibility

**Date:** 2026-10-26  
**Status:** Implementation and automated regression checks complete; physical Windows gesture validation remains open  
**Baseline:** Commit `965c013`; see [LS-BE-020A-audit-report.md](./LS-BE-020A-audit-report.md)

## Root causes addressed

- The previous global gesture path inferred dragged files from Shell `SelectedItems()`. Explorer selection is not proof of the actual OLE drag payload and could cause conversion of unrelated files.
- A synthetic global-menu click could use stale hover state rather than an actual drop on a format sector.
- Radial drawing and sector hit testing used inconsistent angles in the no-hover global state.
- The project virtual environment was Python 3.11.9 but initially lacked its declared runtime and development packages. Running with globally installed Python 3.14 concealed environment-specific test failures.
- RapidOCR 1.4.4 did not match the code's expected model/API and regressed OCR assertions; the declared dependency now stays within the tested 1.2 series. Two test doubles also relied on behavior incompatible with Python 3.11.

## Changes

- New profiles default global gesture monitoring to **OFF**. Users must explicitly enable it; existing saved preferences are preserved.
- Global Shift+drag opens an awaiting-drop target without inferred paths. Conversion is dispatched only after Qt receives a drop containing the exact, validated local-file URL payload and the user drops on a format sector. Shell selections are never substituted.
- Drop validation rejects non-local, mixed remote/local, symlink, non-file, inaccessible, oversized, and unsupported payloads as a whole. Multiple files must share a conversion target. Conversion retains planner/preflight validation and never executes dropped files.
- Shift release, Escape, monitoring-off, timeout, unsupported payload, and drop outside a sector do not dispatch conversion. The in-app drop target uses the same path validation.
- Diagnostic logging records gesture state, payload count, and rejection reason, not dropped paths or contents. The interactive script adds a source-specific manual checklist.
- Added `scripts/run_tests.ps1` to use `.venv\Scripts\python.exe`, the repository `src` directory, and Qt offscreen mode consistently on Windows.
- Settings and README explain opt-in behavior, limitations, and privacy. The legacy Shell selection helpers remain in the module for compatibility but are not called by the active gesture controller.

## Source compatibility matrix

| Source | Implemented path | Evidence and status |
|---|---|---|
| Files dropped onto LocalShift | Qt OLE URL payload; local-file validation | Automated synthetic Qt tests pass. This verifies the app-targeted handling only, not external Windows OLE routing. |
| Windows File Explorer | Global target awaits the actual Qt OLE drop; no selected-file query | **Not physically tested; support not certified.** |
| Windows Desktop | Same actual-drop requirement as Explorer | **Not physically tested; support not certified.** |
| Third-party file managers | Same actual-drop requirement; only local file URL payloads accepted | **No third-party application tested; support not certified.** |
| Browsers, virtual items, remote URLs, archive viewers | No virtual-item extraction or remote download | Rejected unless the source provides an actual local-file URL. Use Open Files or a local-file drop instead. |

No universal cross-application support claim is made. Whether Windows delivers external OLE drops to the non-activating radial target is a key unresolved UI/runtime behavior.
The controller currently waits 500 ms after physical mouse release for the OLE drop event before dismissing the target. Slow or differently ordered source events may time out safely without converting; this timing must be checked in the physical source matrix.

## Environment and automated verification

Project environment: Python **3.11.9** in `.venv`, satisfying `requires-python = ">=3.10"`. No Python version change was made. Development and desktop requirements were installed into that environment. `rapidocr-onnxruntime` is constrained to `>=1.2.3,<1.3`.

| Command/check | Result |
|---|---|
| Initial full suite in restored venv, before fixes | 681 passed, 3 skipped, 9 failed |
| Focused converter/OCR/reliability/radial/shell/GUI tests after fixes | 211 passed, 3 skipped |
| `scripts/verify_windows_gesture.py --check` | Passed all automated route and destination-precedence checks |
| `compileall -q src tests scripts` | Passed |
| `.\scripts\run_tests.ps1` final run after warning fix | **694 passed, 3 skipped, 0 failed** in 169.34 s |
| Skip reasons | Three symlink tests require Windows Developer Mode/admin permissions or `LOCALSHIFT_TEST_SYMLINKS=1` |
| Final suite warnings | None |
| Physical Explorer/Desktop/third-party drag, mixed DPI, output correctness/source hash | **Not performed** |

The automated suite does not establish physical behavior for Explorer, Desktop, third-party file managers, mixed DPI, menu flicker/focus, actual output correctness, or source immutability.

## Manual Windows verification

Run from the repository root:

```powershell
.\.venv\Scripts\python.exe scripts\verify_windows_gesture.py --interactive --log-file .\gesture-diagnostics.log
```

Record each source separately. For Explorer and Desktop, test one file and multiple files (including mixed supported formats); compare dragged items with outputs and verify unselected files are untouched. Also test at least one third-party file manager, virtual/remote payload rejection, ON/OFF, Shift release, Escape, cancellation, mixed DPI/multiple monitors, output collisions, conversion failure, and source hashes before/after. Remove the diagnostic log after review if no longer needed; it should not contain paths or file contents.

## Remaining completion gate

Milestone 20's code and automated checks are complete, but criteria requiring physical Windows interaction remain unverified. Run the checklist above before claiming any external source is supported. No later milestone is started.
