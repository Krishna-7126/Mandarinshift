# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller specification file for LocalShift Windows Packaging.

Builds a reproducible onedir desktop bundle containing:
- LocalShift.exe (Windowed GUI application)
- localshift-cli.exe (Console CLI application)
- Native dependencies (pdfium.dll, onnxruntime.dll)
- Bundled OCR models (rapidocr_onnxruntime ONNX models)
- Microsoft Word template assets (python-docx)
- Application branding icon (assets/icon.ico)
"""

import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

block_cipher = None

# Root paths
spec_root = Path(SPECPATH).resolve()
repo_root = spec_root.parent
src_dir = repo_root / "src"

# Collect RapidOCR onnx models and configs
rapidocr_datas = collect_data_files('rapidocr_onnxruntime')

# Collect pypdfium2 native DLLs
pdfium_binaries = collect_dynamic_libs('pypdfium2_raw')
pdfium_datas = collect_data_files('pypdfium2_raw')

# Collect onnxruntime native binaries
onnx_binaries = collect_dynamic_libs('onnxruntime')

# Collect python-docx templates
docx_datas = collect_data_files('docx')

# Application icon and assets
extra_datas = [
    (str(repo_root / "assets" / "icon.ico"), "assets"),
    (str(repo_root / "assets" / "icon.png"), "assets"),
]

all_datas = rapidocr_datas + pdfium_datas + docx_datas + extra_datas
all_binaries = pdfium_binaries + onnx_binaries

# Shared hidden imports
hidden_imports = [
    'localshift',
    'localshift.cli',
    'localshift.gui',
    'localshift.converter',
    'localshift.exceptions',
    'localshift.formats',
    'localshift.jobs',
    'localshift.models',
    'localshift.planner',
    'localshift.registry',
    'localshift.radial_menu',
    'localshift.settings',
    'localshift.shell_integration',
    'localshift.adapters',
    'localshift.adapters.image',
    'localshift.documents',
    'localshift.documents.adapter',
    'localshift.documents.docx_adapter',
    'localshift.documents.docx_builder',
    'localshift.documents.docx_renderer',
    'localshift.documents.image_to_pdf',
    'localshift.documents.ocr',
    'localshift.documents.pdf_image_exporter',
    'localshift.documents.pdf_inspector',
    'localshift.documents.pdf_workbench',
    'localshift.documents.pdf_tool_registry',
    'localshift.documents.pdf_tools_engine',
    'localshift.documents.renderer',
    'localshift.documents.text_extractor',
    'localshift.pdf_suite_ui',
    'PIL',
    'PIL.PngImagePlugin',
    'PIL.JpegImagePlugin',
    'PIL.WebPImagePlugin',
    'PIL.BmpImagePlugin',
    'PIL.TiffImagePlugin',
    'pypdfium2',
    'pypdfium2_raw',
    'docx',
    'rapidocr_onnxruntime',
    'rapidocr_onnxruntime.ch_ppocr_v2_cls',
    'rapidocr_onnxruntime.ch_ppocr_v2_cls.text_cls',
    'rapidocr_onnxruntime.ch_ppocr_v3_det',
    'rapidocr_onnxruntime.ch_ppocr_v3_det.text_detect',
    'rapidocr_onnxruntime.ch_ppocr_v3_rec',
    'rapidocr_onnxruntime.ch_ppocr_v3_rec.text_recognize',
    'onnxruntime',
    'cv2',
    'numpy',
    'yaml',
]

# Exclude unnecessary heavy packages in environment
excluded_modules = [
    'tkinter',
    'unittest',
    'email',
    'http',
    'xmlrpc',
    'pydoc',
    'test',
    'tests',
    # Qt unused modules
    'PySide6.QtWebEngineCore',
    'PySide6.QtWebEngineWidgets',
    'PySide6.QtWebEngineQuick',
    'PySide6.QtQuick',
    'PySide6.QtQml',
    'PySide6.Qt3DCore',
    'PySide6.Qt3DRender',
    'PySide6.QtDesigner',
    'PySide6.QtBluetooth',
    'PySide6.QtNfc',
    'PySide6.QtSensors',
    'PySide6.QtSerialPort',
    'PySide6.QtSpatialAudio',
    'PySide6.QtMultimedia',
    'PySide6.QtMultimediaWidgets',
    'PySide6.QtPdf',
    'PySide6.QtPdfWidgets',
    # Unused heavy third-party packages in user environment
    'torch',
    'torchvision',
    'torchaudio',
    'tensorflow',
    'scipy',
    'sklearn',
    'transformers',
    'numba',
    'llvmlite',
    'matplotlib',
    'pandas',
    'yt_dlp',
    'opentelemetry',
    'IPython',
    'notebook',
    'jupyter',
    'pytest',
    'pip',
    'wheel',
    'setuptools',
]

# 1. GUI Executable Analysis
a_gui = Analysis(
    [str(spec_root / 'entrypoint_gui.py')],
    pathex=[str(src_dir)],
    binaries=all_binaries,
    datas=all_datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excluded_modules,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz_gui = PYZ(a_gui.pure, a_gui.zipped_data, cipher=block_cipher)

exe_gui = EXE(
    pyz_gui,
    a_gui.scripts,
    [],
    exclude_binaries=True,
    name='LocalShift',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # Windowed GUI
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(repo_root / 'assets' / 'icon.ico'),
    version=str(spec_root / 'version_info.txt'),
)

# 2. CLI Executable Analysis
a_cli = Analysis(
    [str(spec_root / 'entrypoint_cli.py')],
    pathex=[str(src_dir)],
    binaries=all_binaries,
    datas=all_datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excluded_modules,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz_cli = PYZ(a_cli.pure, a_cli.zipped_data, cipher=block_cipher)

exe_cli = EXE(
    pyz_cli,
    a_cli.scripts,
    [],
    exclude_binaries=True,
    name='localshift-cli',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,  # Console CLI
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(repo_root / 'assets' / 'icon.ico'),
    version=str(spec_root / 'version_info.txt'),
)

# Combined COLLECT for single onedir deployment
coll = COLLECT(
    exe_gui,
    a_gui.binaries,
    a_gui.zipfiles,
    a_gui.datas,
    exe_cli,
    a_cli.binaries,
    a_cli.zipfiles,
    a_cli.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='LocalShift',
)
