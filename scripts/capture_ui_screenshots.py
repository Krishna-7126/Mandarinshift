"""scripts/capture_ui_screenshots.py — Render and capture visual screenshots of the redesigned
LocalShift GUI, Settings, Radial Conversion Menu, Completion, and Error states.
"""
from __future__ import annotations

import os
from pathlib import Path
from PIL import Image

# Use offscreen QPA for headless capture
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QPoint, QSize
from PySide6.QtWidgets import QApplication

from localshift.gui import MainWindow, SettingsDialog
from localshift.radial_menu import RadialConversionMenu


def main():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])

    out_dir = Path("docs/screenshots")
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. Create sample test files
    temp_dir = Path("build/screenshot_assets")
    temp_dir.mkdir(parents=True, exist_ok=True)

    png_path = temp_dir / "tangerine_tree.png"
    Image.new("RGB", (320, 240), color=(249, 115, 22)).save(png_path)  # Vibrant orange

    doc_path = temp_dir / "annual_quarterly_report.pdf"
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument.new()
    pdf.new_page(300, 400)
    pdf.save(str(doc_path))
    pdf.close()

    # 2. Main Window Dark Mode
    win = MainWindow()
    win.resize(1020, 680)
    win.show()
    app.processEvents()

    pix = win.grab()
    pix.save(str(out_dir / "02_main_window_dark.png"))
    print("Saved 02_main_window_dark.png")

    # 3. Main Window Light Mode
    win.toggle_theme()
    app.processEvents()
    pix = win.grab()
    pix.save(str(out_dir / "01_main_window_light.png"))
    print("Saved 01_main_window_light.png")

    # Switch back to dark mode
    win.toggle_theme()
    app.processEvents()

    # 4. Conversion Queue
    win.convert_tab.add_paths([png_path, doc_path])
    app.processEvents()
    pix = win.grab()
    pix.save(str(out_dir / "03_conversion_queue.png"))
    print("Saved 03_conversion_queue.png")

    # 5. Conversion Completion State
    win.convert_tab.result_label.setText("✔ Successfully converted all 2 file(s).")
    win.convert_tab.result_banner.setVisible(True)
    win.convert_tab.bar.setValue(100)
    app.processEvents()
    pix = win.grab()
    pix.save(str(out_dir / "06_conversion_completion.png"))
    print("Saved 06_conversion_completion.png")

    # 6. Conversion Error State
    win.convert_tab.result_label.setText("⚠ Completed with issues: 1/2 succeeded, 1 failed.")
    win.convert_tab.result_banner.setStyleSheet("""
        QFrame#resultBanner {
            background-color: #2a1215;
            border: 1px solid #7f1d1d;
            border-radius: 8px;
        }
    """)
    win.convert_tab.table.setItem(1, 3, win.convert_tab.table.item(0, 3).clone())
    win.convert_tab.table.item(1, 3).setText("Failed")
    app.processEvents()
    pix = win.grab()
    pix.save(str(out_dir / "07_conversion_error_state.png"))
    print("Saved 07_conversion_error_state.png")

    win.hide()

    # 7. Floating Radial Menu
    menu = RadialConversionMenu([png_path])
    menu.show()
    menu.set_hover_index(1)  # Highlight second target format
    app.processEvents()
    pix_radial = menu.grab()
    pix_radial.save(str(out_dir / "04_radial_conversion_menu.png"))
    print("Saved 04_radial_conversion_menu.png")
    menu.close()

    # 8. Save-to-Folder Settings Dialog
    settings_dlg = SettingsDialog(win)
    settings_dlg.resize(560, 520)
    settings_dlg.show()
    app.processEvents()
    pix_settings = settings_dlg.grab()
    pix_settings.save(str(out_dir / "05_settings_save_to_folder.png"))
    print("Saved 05_settings_save_to_folder.png")
    settings_dlg.close()

    print("All 7 screenshots captured successfully in docs/screenshots/")


if __name__ == "__main__":
    main()
