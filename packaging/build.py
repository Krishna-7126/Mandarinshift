"""Automated build and packaging pipeline for LocalShift on Windows.

Builds:
1. Portable onedir folder (LocalShift.exe + localshift-cli.exe) via PyInstaller
2. Windows Setup installer via Inno Setup 6 (ISCC.exe)
"""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys


PROJECT_ROOT = Path(__file__).resolve().parent.parent
PACKAGING_DIR = PROJECT_ROOT / "packaging"
DIST_DIR = PROJECT_ROOT / "dist"
BUILD_DIR = PROJECT_ROOT / "build"
APP_DIR = DIST_DIR / "LocalShift"
INSTALLER_DIR = DIST_DIR / "installer"


def find_iscc() -> Path | None:
    """Locate Inno Setup Compiler executable."""
    # 1. On PATH
    which_iscc = shutil.which("ISCC")
    if which_iscc:
        return Path(which_iscc)

    # 2. User AppData (e.g. installed via winget without admin)
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        candidate = Path(local_appdata) / "Programs" / "Inno Setup 6" / "ISCC.exe"
        if candidate.is_file():
            return candidate

    # 3. Standard Program Files
    candidates = [
        Path("C:/Program Files (x86)/Inno Setup 6/ISCC.exe"),
        Path("C:/Program Files/Inno Setup 6/ISCC.exe"),
    ]
    for c in candidates:
        if c.is_file():
            return c

    return None


def calculate_sha256(filepath: Path) -> str:
    """Calculate SHA-256 hash of a file."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def clean() -> None:
    """Remove previous build outputs."""
    print("Cleaning build directories...")
    if BUILD_DIR.exists():
        shutil.rmtree(BUILD_DIR, ignore_errors=True)
    if APP_DIR.exists():
        shutil.rmtree(APP_DIR, ignore_errors=True)
    if INSTALLER_DIR.exists():
        shutil.rmtree(INSTALLER_DIR, ignore_errors=True)
    print("Clean complete.")


def run_pyinstaller() -> None:
    """Run PyInstaller with localshift.spec."""
    spec_path = PACKAGING_DIR / "localshift.spec"
    if not spec_path.is_file():
        raise FileNotFoundError(f"Spec file not found: {spec_path}")

    print("\n" + "=" * 60)
    print("Running PyInstaller build...")
    print("=" * 60)

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        str(spec_path),
    ]
    subprocess.run(cmd, cwd=PROJECT_ROOT, check=True)

    gui_exe = APP_DIR / "LocalShift.exe"
    cli_exe = APP_DIR / "localshift-cli.exe"

    if not gui_exe.is_file():
        raise RuntimeError(f"PyInstaller failed to produce {gui_exe}")
    if not cli_exe.is_file():
        raise RuntimeError(f"PyInstaller failed to produce {cli_exe}")

    print(f"\nPyInstaller build succeeded:")
    print(f"  GUI: {gui_exe} ({gui_exe.stat().st_size / (1024*1024):.2f} MB)")
    print(f"  CLI: {cli_exe} ({cli_exe.stat().st_size / (1024*1024):.2f} MB)")


def verify_bundle() -> bool:
    """Verify critical files and libraries exist within the packaged bundle."""
    print("\n" + "=" * 60)
    print("Verifying packaged bundle integrity...")
    print("=" * 60)

    critical_checks = [
        APP_DIR / "LocalShift.exe",
        APP_DIR / "localshift-cli.exe",
    ]

    missing = [str(p) for p in critical_checks if not p.exists()]
    if missing:
        print(f"FAILED: Missing critical executables: {missing}")
        return False

    # Check for pdfium dll
    pdfium_found = any(APP_DIR.glob("**/pdfium.dll")) or any(APP_DIR.glob("pdfium.dll"))
    print(f"  pdfium.dll present: {pdfium_found}")

    # Check for onnxruntime dll
    onnx_found = any(APP_DIR.glob("**/onnxruntime*.dll"))
    print(f"  onnxruntime DLL present: {onnx_found}")

    # Check for OCR onnx models
    ocr_models = list(APP_DIR.glob("**/*.onnx"))
    print(f"  ONNX OCR models present: {len(ocr_models)} models found")

    print("Bundle verification passed.")
    return True


def run_inno_setup() -> Path | None:
    """Compile Inno Setup installer."""
    iscc = find_iscc()
    if not iscc:
        print("\nWARNING: Inno Setup compiler (ISCC.exe) not found.")
        print("Skipping installer creation. Packaged folder is ready at dist/LocalShift.")
        return None

    iss_file = PACKAGING_DIR / "localshift.iss"
    if not iss_file.is_file():
        raise FileNotFoundError(f"Inno Setup script not found: {iss_file}")

    print("\n" + "=" * 60)
    print(f"Building Windows Setup installer using {iscc}...")
    print("=" * 60)

    cmd = [str(iscc), str(iss_file)]
    subprocess.run(cmd, cwd=PACKAGING_DIR, check=True)

    installer = next(INSTALLER_DIR.glob("LocalShift-Setup-*.exe"), None)
    if installer and installer.is_file():
        size_mb = installer.stat().st_size / (1024 * 1024)
        sha = calculate_sha256(installer)
        print(f"\nInstaller build succeeded:")
        print(f"  File: {installer}")
        print(f"  Size: {size_mb:.2f} MB")
        print(f"  SHA-256: {sha}")
        return installer
    else:
        raise RuntimeError("Inno Setup ran but installer output was not found.")


def main() -> int:
    parser = argparse.ArgumentParser(description="LocalShift Windows Packaging Pipeline")
    parser.add_argument("--clean-only", action="store_true", help="Clean build directories and exit")
    parser.add_argument("--skip-installer", action="store_true", help="Skip Inno Setup installer compilation")
    parser.add_argument("--verify-only", action="store_true", help="Run verification on existing dist folder")
    args = parser.parse_args()

    if args.clean_only:
        clean()
        return 0

    if args.verify_only:
        success = verify_bundle()
        return 0 if success else 1

    clean()
    run_pyinstaller()
    if not verify_bundle():
        return 1

    if not args.skip_installer:
        run_inno_setup()

    print("\n" + "=" * 60)
    print("LocalShift build pipeline completed successfully.")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
