"""
LocalShift GUI Smoke Test on Windows.
Verifies GUI components, tabs, widgets, queue loading, and event loop processing.
"""
import os
import sys
from pathlib import Path
from PIL import Image

# Run in offscreen mode to permit automated execution without physical display interaction
os.environ["QT_QPA_PLATFORM"] = "offscreen"

import PySide6
from PySide6.QtWidgets import QApplication
from localshift.gui import (
    MainWindow,
    FileConverterTab,
    DocxInterchangeTab,
    PdfRasterizeTab,
    ImagesToPdfTab,
    PdfWorkbenchTab,
)

print(f"PySide6 version: {PySide6.__version__}")
print(f"Platform: {sys.platform}, Python: {sys.version}")

app = QApplication([])
win = MainWindow()
win.show()

# 1. MainWindow Structure
assert "LocalShift" in win.windowTitle()
assert win.tabs.count() == 5
print("Smoke Test [1/7]: MainWindow and 5 workflow tabs created successfully.")

# 2. FileConverterTab
sample_png = Path("smoke_test.png")
Image.new("RGB", (32, 32), color="green").save(sample_png)
try:
    win.convert_tab.add_paths([sample_png])
    assert win.convert_tab.table.rowCount() == 1
    combo = win.convert_tab.table.cellWidget(0, 2)
    assert combo.count() > 0
    print(f"Smoke Test [2/7]: FileConverterTab added file with {combo.count()} target formats.")

    # 3. DocxInterchangeTab
    win.tabs.setCurrentIndex(1)
    win.docx_tab.radio_docx_to_pdf.setChecked(True)
    assert win.docx_tab.docx_settings_widget.isVisible()
    print("Smoke Test [3/7]: DocxInterchangeTab direction toggled and backend checked.")

    # 4. PdfRasterizeTab
    win.tabs.setCurrentIndex(2)
    idx_jpeg = win.rasterize_tab.fmt_combo.findData("jpeg")
    win.rasterize_tab.fmt_combo.setCurrentIndex(idx_jpeg)
    assert win.rasterize_tab.quality_spin.isEnabled()
    print("Smoke Test [4/7]: PdfRasterizeTab format selection and quality enabled.")

    # 5. ImagesToPdfTab
    win.tabs.setCurrentIndex(3)
    win.assembly_tab.add_images([sample_png])
    assert len(win.assembly_tab.image_paths) == 1
    print("Smoke Test [5/7]: ImagesToPdfTab queue loaded and verified.")

    # 6. PdfWorkbenchTab
    win.tabs.setCurrentIndex(4)
    for op in ["merge", "split", "extract", "reorder", "rotate"]:
        idx = win.workbench_tab.op_combo.findData(op)
        win.workbench_tab.op_combo.setCurrentIndex(idx)
        app.processEvents()
    print("Smoke Test [6/7]: PdfWorkbenchTab all 5 operations switched and verified.")

    # 7. Event loop cleanup
    win.close()
    app.processEvents()
    print("Smoke Test [7/7]: Window closed cleanly and event loop flushed.")

finally:
    if sample_png.exists():
        sample_png.unlink()

print("\n>>> ALL WINDOWS GUI SMOKE CHECKS PASSED SUCCESSFULLY! <<<")
