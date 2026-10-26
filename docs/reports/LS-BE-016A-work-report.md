# LocalShift — Milestone 16A Work Report
## Shift + Drag Conversion Workflow, Complete Format Expansion & Global Save Destination

**Date:** 2026-10-26  
**Status:** Implemented, Tested & Verified (586 Passed, 3 Skipped, 0 Failed)  
**Target:** LocalShift v0.15.0-dev

---

### 1. Executive Summary

Milestone 16A resolves the end-to-end Shift + Drag conversion experience, expands offline format capabilities, and adds a persistent application-wide **Save to Folder** setting inspired by LocalSend.

- **Shift + Drag Direct Drop:** Diagnosed root cause of gesture failure in Windows desktop environments. Registered `RadialConversionMenu` as an active Windows OLE drop target (`setAcceptDrops(True)`), added in-flight hover tracking (`dragMoveEvent`) with geometric petal hit-testing (`petal_at_pos`), and enabled direct drop onto petals (`dropEvent`) with immediate conversion (`auto_start=True`) and completion notification banners offering "Open File(s)" and "Open Folder".
- **Centralized "Save to Folder" Setting:** Implemented `src/localshift/settings.py` (`AppSettings`) backed by `QSettings`. Includes active folder validation (`validate_destination_directory`) with test sentinels to verify true write accessibility, a dedicated `SettingsDialog` with status indicators, and a strict destination resolution policy applied uniformly across all 5 GUI tabs.
- **Format Expansion to 54 Routes:** Added `GIF` (adaptive paletting, transparency preservation) and `ICO` (clamped to 256×256 with Lanczos resampling, RGBA) to Pillow raster adapter and `ImageToPdfAdapter`, increasing verified offline conversion routes from 30 to 54.

---

### 2. Files Created & Modified

#### Created Files
- `src/localshift/settings.py`: Centralized `AppSettings` singleton and `validate_destination_directory` / `resolve_destination` policies.
- `tests/test_settings.py`: Automated tests covering persistence, write-access probing, and resolution hierarchy.
- `scripts/capture_ui_screenshots.py`: Headless visual rendering script capturing main window, queue, radial menu, and settings dialog.
- `docs/screenshots/`: Rendered visual artifacts (`01` through `05`).
- `docs/reports/LS-BE-016A-work-report.md`: Milestone report.

#### Modified Files
- `src/localshift/radial_menu.py`: Added OLE drop handling (`setAcceptDrops(True)`), `petal_at_pos` geometric hit-testing, `dragMoveEvent`, `dropEvent`, and `set_paths`.
- `src/localshift/gui.py`: Added `SettingsDialog`, wired `resolve_destination` into all 5 tabs, added drag-move Shift detection, and hooked `auto_start=True` to radial format execution.
- `src/localshift/formats.py`: Registered `gif` and `ico` format keys, descriptions, and extensions.
- `src/localshift/adapters/image.py`: Added `gif` and `ico` to `IMAGE_FORMATS` and `PIL_SAVE_FORMATS`, implemented mode coercions for ICO (256x256 max) and GIF (P with transparency).
- `src/localshift/documents/image_to_pdf.py`: Added `gif` and `ico` to `SUPPORTED_IMAGE_FORMATS`.
- `tests/test_radial_menu.py`: Added tests for dynamic `set_paths`, `petal_at_pos`, drag enter/move, and drop on petal simulation.
- `tests/test_adapters.py`: Added tests for GIF and ICO round-trip raster conversion, mode coercions, and route expansion.
- `tests/test_planning.py`: Updated expected format sets, route counts (54 routes), and adapter counts (42 raster routes).
- `docs/FORMAT_SUPPORT.md`: Documented 54 routes, GIF/ICO behavior, and options.
- `docs/ARCHITECTURE.md`: Documented `AppSettings` service and OLE drag & drop event architecture.
- `docs/PROJECT_STATUS.md`: Recorded Milestone 16A status and test metrics.
- `CHANGELOG.md` & `README.md`: Documented new capabilities and updated user guides.

---

### 3. Root Cause of Previous Shift Gesture Failure

1. **Windows OLE Drag Ownership:** During an external file drag originated from Windows File Explorer or the Desktop, the source process and Windows OLE (`DoDragDrop`) maintain global mouse capture. Standard background Qt windows receive **zero** mouse or keyboard events while the cursor is outside their window boundaries.
2. **Missing Drop Target on Radial Menu:** The previous radial menu had `acceptDrops()` set to `False` (Qt default). When the menu popped up under the cursor during an active drag, the Windows OLE subsystem treated the menu as a non-drop target (`DROPEFFECT_NONE`), preventing the user from dropping onto the menu petals.
3. **Event Hijacking Avoidance:** Installing low-level global Windows keyboard hooks (`WH_KEYBOARD_LL`) outside Qt creates security warnings, potential antivirus false positives, and breaks when running with standard user privileges.
4. **The Working Architecture:** By registering `RadialConversionMenu` as an active drop target (`setAcceptDrops(True)`) with `dragMoveEvent` and `dropEvent` handlers, the active drag seamlessly flows into the radial menu the moment it appears, allowing direct hovering and dropping onto individual petals.

---

### 4. Exact Supported Gesture Behavior

1. **Shift + Drag Drop Workflow:**
   - User drags one or more files from Windows File Explorer or Desktop into LocalShift while holding the `Shift` key (or begins dragging within LocalShift with `Shift` held).
   - LocalShift detects the active drag with `Qt.ShiftModifier` and displays `RadialConversionMenu` centered directly under the drag cursor.
   - As the user moves the mouse across the radial wheel (still holding the mouse button), `dragMoveEvent` evaluates `petal_at_pos(pos)` and dynamically highlights the petal under the cursor.
   - Dropping the files onto a target format petal (`dropEvent`) selects the format, closes the menu, and automatically launches conversion (`auto_start=True`).
   - A non-intrusive status banner appears with "Open File" and "Open Folder" actions upon completion.
2. **Alternative Keyboard / Menu Workflows:**
   - Files can be added to the queue normally. Pressing `Shift` or `Shift + Space` pops up the radial menu.
   - Keyboard navigation via `Tab`, `Arrow keys`, `1`-`9`, `Enter` to convert, and `Esc` to dismiss.

---

### 5. Save to Folder Behavior & Precedence Rules

1. **Centralized Service:** `src/localshift/settings.py` (`AppSettings`) provides persistent configuration via Windows `QSettings`.
2. **Validation:** `validate_destination_directory(path)` verifies directory existence and active write permissions by creating and removing a temporary `.localshift_write_test_*` probe file.
3. **Resolution Hierarchy:**
   - **Rule 1 (Explicit Job Destination):** If a conversion job explicitly specifies an output directory (e.g. CLI `--output-dir` or tab destination picker), that destination is strictly used.
   - **Rule 2 (Global Destination):** If no explicit job override is given, and `save_to_folder_enabled` is `True` and the folder is verified accessible/writable, outputs are directed to `save_to_folder_path`.
   - **Rule 3 (Workflow Fallback):** If disabled, invalid, or inaccessible, conversion defaults to the source file's directory or the workflow's configured default.

---

### 6. Conversion Coverage Matrix (54 Total Routes)

| Source Format | Target Formats | Adapter | Engine / Backend |
|---|---|---|---|
| `png` | `bmp`, `gif`, `ico`, `jpeg`, `pdf`, `tiff`, `webp` | `PillowImageAdapter` / `ImageToPdfAdapter` | Pillow / PDFium |
| `jpeg` / `jpg` | `bmp`, `gif`, `ico`, `pdf`, `png`, `tiff`, `webp` | `PillowImageAdapter` / `ImageToPdfAdapter` | Pillow / PDFium |
| `webp` | `bmp`, `gif`, `ico`, `jpeg`, `pdf`, `png`, `tiff` | `PillowImageAdapter` / `ImageToPdfAdapter` | Pillow / PDFium |
| `bmp` | `gif`, `ico`, `jpeg`, `pdf`, `png`, `tiff`, `webp` | `PillowImageAdapter` / `ImageToPdfAdapter` | Pillow / PDFium |
| `tiff` / `tif` | `bmp`, `gif`, `ico`, `jpeg`, `pdf`, `png`, `webp` | `PillowImageAdapter` / `ImageToPdfAdapter` | Pillow / PDFium |
| `gif` | `bmp`, `ico`, `jpeg`, `pdf`, `png`, `tiff`, `webp` | `PillowImageAdapter` / `ImageToPdfAdapter` | Pillow / PDFium |
| `ico` | `bmp`, `gif`, `jpeg`, `pdf`, `png`, `tiff`, `webp` | `PillowImageAdapter` / `ImageToPdfAdapter` | Pillow / PDFium |
| `pdf` | `txt`, `docx`, `png`, `jpeg` | `PdfDocumentAdapter` | PDFium / RapidOCR / docx |
| `docx` | `pdf` | `DocxToPdfAdapter` | LibreOffice / Word COM |

---

### 7. New Dependencies and Licenses

- **Zero new third-party dependencies were introduced.**
- `gif` and `ico` formats are natively supported by the existing, verified `Pillow` engine (HPND/PIL license).
- `QSettings` is provided by `PySide6` (LGPL-3).

---

### 8. Test Commands & Actual Results

```powershell
# Targeted test runs
py -3.14 -m pytest tests/test_settings.py tests/test_radial_menu.py tests/test_adapters.py tests/test_planning.py
# Result: 84 passed in 5.95s

# Full test suite execution
py -3.14 -m pytest
# Result: 586 passed, 3 skipped, 0 failed in 117.58s
```

---

### 9. Known Limitations & Risks

1. **Cross-Window File Explorer Drag Detection:** External drag tracking is constrained by Windows OLE security boundaries; the drag cursor must cross into LocalShift's window space for the radial menu to activate.
2. **Multi-Frame GIF Conversion:** Converting animated GIFs to single-frame raster targets converts the primary/first frame; multi-frame animation playback/splitting remains an area for future format expansion.

---

### 10. Next Recommended Milestone

- **Milestone 16B (Audio & Video Adapter Feasibility):** Add optional external FFmpeg backend detection for offline audio (WAV, MP3, FLAC, AAC, OGG) and video container transformations.
