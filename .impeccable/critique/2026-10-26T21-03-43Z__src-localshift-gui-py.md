---
target: LocalShift actual Windows desktop UI
total_score: 20
max_score: 40
na_heuristics: 
p0_count: 0
p1_count: 5
target_identity: "file:Z:\\LocalShift\\src\\localshift\\gui.py"
target_fingerprint: "sha256:ac653c050c945276ad50511be8cb400e60e9bb3c79aa40fecbd8a9b958a60254"
target_path: "Z:\\LocalShift\\src\\localshift\\gui.py"
timestamp: 2026-10-26T21-03-43Z
slug: src-localshift-gui-py
---
# LocalShift UI critique — native desktop review

Method: design review only (detector not applicable, native PySide6 desktop). Assessment A was an isolated read-only source and screenshot review; no physical Windows behavior was inferred. No browser overlay was run because this is not a web-rendered application.

## Design specificity
Moderately product-specific in workflow, weakly distinctive in visual expression. Local file conversion, the work queue, PDF workflows, and radial conversion are LocalShift-specific, but the main window leans on generic dashboard cards, a gradient call-to-action, and a large equal-weight catalog. The radial menu is the clearest product-specific interaction. Keep existing product function and privacy truth; replace the generic visual treatment with a restrained, platform-native working tool.

## Nielsen scores (0-4)
1. Visibility of system status — 2: queue, destination and completion are represented, but compete with many panels.
2. Match with real world — 2: browse and queue are familiar; OCR and PDF settings expose technical language too early.
3. User control and freedom — 3: remove/clear, cancel, Escape and explicit destinations exist.
4. Consistency and standards — 1: suite/dialog colors are hard-coded separately from themes; shortcut messaging varies.
5. Error prevention — 2: destination and payload validation exist, but irrelevant options remain visible and empty search has no recovery state.
6. Recognition rather than recall — 2: browse/search/format choices help, but the large catalog and jargon make discovery harder.
7. Flexibility and efficiency — 3: batch, drag/drop and keyboard/radial paths exist; cues are inconsistent.
8. Aesthetic and minimalist design — 1: cards, repeated controls, fixed options and broad catalog compete.
9. Error recovery — 2: some error/status handling exists, but recovery is not consistently close to the failed action.
10. Help and documentation — 2: README is extensive but feature-heavy; committed screenshots show square glyphs and are not reliable proof of legible UI.

**Total: 20/40 — significant usability and visual improvement needed.**

## Cognitive load
Failures: single focus (multiple actions and panels compete); chunking (more than four settings/actions grouped together); hierarchy (cards and gradients elevate secondary items); minimal choices (32 catalog entries and several persistent conversion options); progressive disclosure (PDF/JPEG/OCR options remain visible when irrelevant); recognition (technical labels and glyph-only/icon cues); feedback (no dedicated empty search state). Overall load is high, particularly for a first-time single-file conversion.

## What works
- The primary convert job is identifiable and supported by browse, drag/drop, queue and explicit target selection.
- Offline/private behavior and gesture limits are disclosed rather than implied.
- The radial menu is a distinctive, product-specific shortcut and retains keyboard interaction.

## Ten biggest verified usability and visual-quality issues
1. **Generic, competing dashboard hierarchy.** In `gui.py`, gradient shortcut surfaces, multiple cards and repeated radial-entry buttons visually compete with the actual queue/conversion action. Give the queue and one clear conversion action first priority; remove repeated promotion.
2. **Width-fragile composition.** `MainWindow` has a fixed 205 px sidebar and 880 px minimum; the queue has five columns and the PDF catalog hard-codes three columns. Reflow or collapse navigation and prioritize columns at narrower widths.
3. **Too many persistent conversion settings.** OCR, DPI, JPEG quality and PDF pages are all visible together in `FileConverterTab`, including for raster-only or DOCX work. Reveal only options relevant to the selected route.
4. **Catalog presents breadth as the navigation model.** `PdfToolsSuiteTab` renders a fixed three-column grid of 32 equal-weight tools beside search and category filters. Organize around common PDF jobs and make the catalog scannable without giving every tool equal prominence.
5. **PDF cards are not keyboard controls.** `ToolCardWidget` is a clickable `QFrame` implemented around mouse events without focus/keyboard activation. Use focusable standard controls with visible focus and activation semantics.
6. **Light theme is not end-to-end.** PDF suite cards/search/dialogs set literal dark colors; the radial menu also paints a hard-coded dark palette. Share theme-aware semantic colors across all windows and test both themes.
7. **Radial text and secondary detail are too small.** The custom wheel uses 7–11 pt text for badges, format labels and guidance, while its hub and pills consume significant area. Keep the format choice primary, remove redundant micro-labels, and scale the remaining copy for legibility.
8. **Radial shortcut cues conflict.** The landing button says “or press Shift”; the header says “Shift” but its tooltip says “Shift or Shift+Space.” Standardize a precise label per activation path and explain global consent separately.
9. **Settings is a long mixed-purpose form.** Save destination, appearance, global gesture, startup, privacy, diagnostic action and About are stacked in one dialog. Group and sequence settings by job; keep privacy and global activation explanation adjacent to its opt-in.
10. **Visual documentation is not legible.** Committed main, radial, settings and result screenshots render much text as square glyphs. Re-capture them from the verified app/font configuration after the UI work; do not use them as current-state proof.

## Personas
- **Keyboard-only/Sam:** PDF catalog cards do not expose standard keyboard focus/activation; hover-centered radial feedback is not sufficient for all users.
- **First-time converter/Jordan:** must parse the persistent options and competing panels before getting from file to target format.
- **Power user/Alex:** fixed columns, repeated radial controls and all-options-at-once layout add scan time instead of making batch setup efficient.

## Theme and size risks
The dark shell is internally more cohesive than the suite; the light theme is demonstrably inconsistent in source due to hard-coded surfaces and text colors. The 880 px minimum, fixed sidebar, 5-column table, horizontal options and fixed 3-column catalog are structural risks at small windows and larger text scales. No physical or live application behavior was measured in this assessment.

## Run notes
The installed `impeccable` command surface reports `detect` and helper commands, not web critique/detector visualization for PySide6; the native-app method applies and web scanning is not applicable. `concept-seed --help` correctly refused to run until product context exists (`NO_PRODUCT_MD`). The project has no PRODUCT.md, DESIGN.md, or critique ignore file. The user's current request already authorizes addressing all ten listed UI surfaces; no scope selection is needed. Before the required design-direction roll, clarify the product's primary audience and most important workflow.
