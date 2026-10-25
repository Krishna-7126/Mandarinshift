"""Tests for packaging configuration, assets, version metadata, and build specifications."""

from pathlib import Path
from PIL import Image
import pytest

from localshift.gui import _find_app_icon


PROJECT_ROOT = Path(__file__).resolve().parent.parent
PACKAGING_DIR = PROJECT_ROOT / "packaging"
ASSETS_DIR = PROJECT_ROOT / "assets"


def test_packaging_files_exist():
    expected_files = [
        PACKAGING_DIR / "localshift.spec",
        PACKAGING_DIR / "localshift.iss",
        PACKAGING_DIR / "build.py",
        PACKAGING_DIR / "version_info.txt",
        PACKAGING_DIR / "entrypoint_gui.py",
        PACKAGING_DIR / "entrypoint_cli.py",
    ]
    for p in expected_files:
        assert p.is_file(), f"Missing packaging file: {p}"


def test_assets_exist_and_valid():
    ico_path = ASSETS_DIR / "icon.ico"
    png_path = ASSETS_DIR / "icon.png"

    assert ico_path.is_file(), f"Missing icon.ico at {ico_path}"
    assert png_path.is_file(), f"Missing icon.png at {png_path}"

    with Image.open(png_path) as img:
        assert img.size == (256, 256)
        assert img.format == "PNG"

    with Image.open(ico_path) as img:
        assert img.format == "ICO"
        # Check that multiple resolutions exist
        assert hasattr(img, "ico") or img.size[0] > 0


def test_version_info_metadata():
    import localshift
    assert localshift.__version__ == "0.14.0"

    version_file = PACKAGING_DIR / "version_info.txt"
    content = version_file.read_text(encoding="utf-8")
    assert "filevers=(0, 14, 0, 0)" in content
    assert "prodvers=(0, 14, 0, 0)" in content
    assert "StringStruct('ProductName', 'LocalShift')" in content
    assert "StringStruct('ProductVersion', '0.14.0.0')" in content


def test_spec_configuration():
    spec_file = PACKAGING_DIR / "localshift.spec"
    content = spec_file.read_text(encoding="utf-8")

    # Verify dual target setup
    assert "entrypoint_gui.py" in content
    assert "entrypoint_cli.py" in content
    assert "name='LocalShift'" in content
    assert "name='localshift-cli'" in content

    # Verify exclusions of unused Qt modules
    assert "PySide6.QtWebEngineCore" in content
    assert "PySide6.QtQml" in content

    # Verify model/lib collection
    assert "rapidocr_onnxruntime" in content
    assert "pypdfium2_raw" in content


def test_inno_setup_configuration():
    iss_file = PACKAGING_DIR / "localshift.iss"
    content = iss_file.read_text(encoding="utf-8")

    assert '#define MyAppName "LocalShift"' in content
    assert '#define MyAppVersion "0.14.0"' in content
    assert "OutputBaseFilename=LocalShift-Setup-{#MyAppVersion}" in content
    assert "UninstallDisplayIcon={app}\\{#MyAppExeName}" in content
    assert "ArchitecturesInstallIn64BitMode=x64compatible" in content


def test_find_app_icon_helper():
    icon_path = _find_app_icon()
    assert icon_path is not None
    assert icon_path.is_file()

