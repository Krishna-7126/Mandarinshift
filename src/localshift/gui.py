from pathlib import Path
import sys
from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (QApplication, QComboBox, QFileDialog, QHBoxLayout,
    QLabel, QMainWindow, QMessageBox, QPushButton, QProgressBar, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget)
from .converter import ConversionError, convert_image
from .formats import FORMAT_LABELS, output_formats_for

class Worker(QThread):
    item_done = Signal(int, str, str)
    all_done = Signal()
    def __init__(self, jobs):
        super().__init__()
        self.jobs = jobs
    def run(self):
        for i, (src, target, outdir) in enumerate(self.jobs):
            try:
                result = convert_image(src, target, outdir)
                self.item_done.emit(i, "Done", str(result))
            except ConversionError as exc:
                self.item_done.emit(i, "Failed", str(exc))
            except Exception as exc:
                self.item_done.emit(i, "Failed", f"Unexpected error: {exc}")
        self.all_done.emit()

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("LocalShift — Offline Converter")
        self.resize(850, 560)
        self.paths = []
        self.output_dir = None
        self.worker = None
        central = QWidget()
        layout = QVBoxLayout(central)
        title = QLabel("LocalShift\nConvert images locally. Originals stay untouched.")
        title.setStyleSheet("font-size: 17px; font-weight: 600; padding: 8px;")
        layout.addWidget(title)
        controls = QHBoxLayout()
        add = QPushButton("Add images…")
        add.clicked.connect(self.pick_files)
        controls.addWidget(add)
        self.add_button = add
        choose = QPushButton("Output: Same folder as source")
        choose.clicked.connect(self.pick_output)
        controls.addWidget(choose)
        self.output_button = choose
        layout.addLayout(controls)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["File", "Convert to", "Status", "Details"])
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table)
        self.table.setAcceptDrops(True)
        self.table.dragEnterEvent = self.drag_enter
        self.table.dropEvent = self.drop_files
        self.setAcceptDrops(True)
        bottom = QHBoxLayout()
        self.bar = QProgressBar()
        bottom.addWidget(self.bar)
        self.convert_button = QPushButton("Convert")
        self.convert_button.clicked.connect(self.convert)
        bottom.addWidget(self.convert_button)
        layout.addLayout(bottom)
        self.setCentralWidget(central)
        self.setStyleSheet("QMainWindow{background:#f5f6fb} QPushButton{background:#4f46e5;color:white;padding:9px;border:0;border-radius:6px} QTableWidget{background:white}")

    def drag_enter(self, event):
        event.acceptProposedAction() if event.mimeData().hasUrls() else event.ignore()
    def drop_files(self, event):
        self.add_paths([Path(u.toLocalFile()) for u in event.mimeData().urls()])
        event.acceptProposedAction()
    def dragEnterEvent(self, event): self.drag_enter(event)
    def dropEvent(self, event): self.drop_files(event)
    def pick_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Add images", "",
            "Images (*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff)")
        self.add_paths([Path(p) for p in paths])
    def pick_output(self):
        chosen = QFileDialog.getExistingDirectory(self, "Select output folder")
        if chosen:
            self.output_dir = Path(chosen)
            self.output_button.setText("Output: " + chosen)
    def add_paths(self, paths):
        for path in paths:
            if not path.is_file() or path in self.paths or not output_formats_for(path):
                continue
            self.paths.append(path)
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(path.name))
            combo = QComboBox()
            for fmt in output_formats_for(path):
                combo.addItem(FORMAT_LABELS[fmt], fmt)
            self.table.setCellWidget(row, 1, combo)
            self.table.setItem(row, 2, QTableWidgetItem("Ready"))
            self.table.setItem(row, 3, QTableWidgetItem(str(path)))
    def convert(self):
        if not self.paths:
            QMessageBox.information(self, "No images", "Add supported images first.")
            return
        jobs = [(p, self.table.cellWidget(i, 1).currentData(), self.output_dir)
                for i, p in enumerate(self.paths)]
        self.convert_button.setEnabled(False)
        self.add_button.setEnabled(False)
        self.bar.setValue(0)
        self.worker = Worker(jobs)
        self.worker.item_done.connect(self.row_done)
        self.worker.all_done.connect(self.done)
        self.worker.start()
    def row_done(self, index, status, detail):
        self.table.setItem(index, 2, QTableWidgetItem(status))
        self.table.setItem(index, 3, QTableWidgetItem(detail))
        self.bar.setValue(int((index + 1) * 100 / len(self.paths)))
    def done(self):
        self.convert_button.setEnabled(True)
        self.add_button.setEnabled(True)
        QMessageBox.information(self, "Finished", "Conversion queue completed.")

def main():
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
