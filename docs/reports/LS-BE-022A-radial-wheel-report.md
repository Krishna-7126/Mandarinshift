# LocalShift Milestone 22A — Radial Wheel & Overlay Reliability

**Date:** 2026-10-27  
**Status:** Code fixes and automated verification complete; physical Windows/display verification remains open  
**Scope:** Milestone 22A only. No new conversion formats, PDF capabilities, redesign, commit, or release claim.

## Audit findings

| Verified cause | User impact | Fix |
|---|---|---|
| The popup's top and bottom pills used fixed widget-edge positions, while the wheel was centered. The app overlay expands to the full main-window size, making the pills and filename appear detached from the wheel. | Floating labels and a visually split wheel/overlay, especially in the in-window overlay. | Position both pills relative to the wheel center and clamp them within the widget. Remove the separate overlay header stranded at the window edge. |
| Hit-testing accepted any point within a broad invisible annulus and converted its angle to a format, although the visible targets are circular petal discs. | Gaps and points outside a visible petal could select a format. | Use the same petal-center calculation for paint and hit-testing; use the visible disc as the target and a distance buffer only for the current hover. |
| A mouse press confirmed the stored hover index without checking where the press occurred. | A click could select a stale format; ignored mouse presses could propagate to underlying controls. | Hit-test the press position, cancel on a gap, and accept the event so it cannot trigger an underlying widget. |
| Overlay geometry was recalculated in `resizeEvent`, but callers can resize and immediately hit-test in the same drag event. | The first drag position after a resize could be tested against the previous wheel center. | Update center coordinates synchronously in `setGeometry` as well as on resize. |
| Menu ownership was tracked separately by the shortcut filter and converter tab, while the main-window overlay and background controller had separate entry points. | A second activation path could open another in-app wheel during an existing interaction. | In-app entry points check for an already visible menu; the background controller suppresses its target while an in-app menu is active. |
| Closing a standalone menu through the window manager did not emit cancellation or delete the hidden child widget. | Stale ownership references and accumulated hidden menu widgets after repeated interactions. | Emit cancellation on external close and use `WA_DeleteOnClose` for standalone menus; overlays remain persistent children. |

No native hooks, injected code, file selection fallback, or conversion behavior was added.

## Changes

- `src/localshift/radial_menu.py`
  - Shared petal-center geometry for drawing and hit-testing.
  - Current-pointer click selection and accepted cancellation clicks.
  - Wheel-relative pill placement and immediate resize coordinate updates.
  - Visible-menu lookup, exactly-once cancellation signaling, and standalone close cleanup.
- `src/localshift/gui.py`
  - Suppress a competing converter popup or in-window overlay when another in-app menu is active.
- `src/localshift/shell_integration.py`
  - Do not open a global gesture target over an active in-app menu.
- `tests/test_radial_menu.py`, `tests/test_gui.py`
  - Coverage for visible petal hit regions, gaps, click position, overlay/popup pill geometry, render completion, cancellation/teardown, and duplicate activation.
- `README.md`, `docs/ARCHITECTURE.md`, `docs/TEST_PLAN.md`, `TASKS.md`, `CHANGELOG.md`
  - Update radial behavior, verification scope, and milestone status.

## Verification

| Check | Result |
|---|---|
| `.\scripts\run_tests.ps1` | **718 passed, 3 skipped, 0 failed** in 164.40 s |
| Skips | Three Windows symlink tests require Developer Mode/admin permissions or `LOCALSHIFT_TEST_SYMLINKS=1`. |
| `.\.venv\Scripts\python.exe -m pytest tests\test_radial_menu.py tests\test_gui.py tests\test_shell_integration.py` | **83 passed** in 7.23 s |
| `.\.venv\Scripts\python.exe -m compileall -q src tests scripts` | Passed |
| `git diff --check` | Passed |
| Qt offscreen rendering | Inspected 400×460 popup and 980×680 overlay renders. The pills remain outside the visible petal bounds in both sizes; this is a software render, not physical display verification. Temporary renders were removed. |

The full suite ran through the repository's Windows launcher and project Python 3.11 environment. The three already-modified PDF fixtures were restored byte-for-byte to their pre-run contents; prior uncommitted changes and diagnostic files were preserved.

## Physical verification status

| Scenario | Status | Evidence |
|---|---|---|
| Explorer — single and multiple files | **NOT TESTED** | No physical drag performed. |
| Desktop — single and multiple files | **NOT TESTED** | No physical drag performed. |
| Third-party file manager | **NOT TESTED** | No application/version recorded. |
| Unsupported or virtual payload | **NOT TESTED** | Automated payload tests only; no physical source interaction. |
| Mixed-DPI monitors and common Windows scaling levels | **NOT TESTED** | No monitor/display interaction performed. |
| Escape, cancellation, Shift release, click-through and repeated open/close | **NOT TESTED physically** | Relevant state and widget behavior have automated Qt tests only. |
| Output correctness and source immutability after external drag | **NOT TESTED** | No external drag conversion performed. |

## Remaining limitations and next action

- External OLE routing, focus behavior, DPI coordinate mapping, multi-monitor placement, and real drag timing remain uncertified. Offscreen Qt tests do not establish Windows Explorer/Desktop compatibility.
- The popup uses Qt logical coordinates and screen-boundary clamping, but this stage did not physically verify unusual small work areas or mixed-DPI monitor transitions.
- The pre-existing Milestone 21 release/performance gates remain open; this stage does not claim release readiness.
- **Next:** perform the Milestone 21 manual Windows verification matrix on the target machine, including screenshots or non-sensitive event evidence where helpful. After that evidence is recorded, continue with Milestone 22B. Do not start conversion-format expansion or the broader redesign before the gesture verification gate is reviewed.
