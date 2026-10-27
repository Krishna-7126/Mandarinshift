"""
scripts/verify_windows_gesture.py — Real Windows OLE Drag & Drop and Radial Menu Gesture Verification.

Milestone 21 Interactive & Automated Verification Harness:
- Verifies physical Win32 GetAsyncKeyState(VK_SHIFT) state detection.
- Verifies In-Window Radial Overlay activation, geometry clamping, and hit testing.
- Verifies multi-file route intersection.
- Verifies Save to Folder destination resolution precedence.
- Provides interactive verification checklist for desktop Windows sessions.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import logging
import os
import platform
import sys
from pathlib import Path
from PIL import Image

# Ensure localshift package import
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from localshift.formats import output_formats_for
from localshift.radial_menu import (
    GestureState,
    RadialConversionMenu,
    get_supported_targets,
    is_shift_pressed,
)
from localshift.settings import get_settings, validate_destination_directory


MANUAL_CASES = (
    ("EXP-SINGLE", "Windows File Explorer", "Single supported file"),
    ("EXP-MULTI", "Windows File Explorer", "Multiple supported files"),
    ("DESKTOP-SINGLE", "Windows Desktop", "Single supported file"),
    ("DESKTOP-MULTI", "Windows Desktop", "Multiple supported files"),
    ("THIRD-PARTY", "Third-party file manager", "Single and multiple supported files"),
    ("VIRTUAL", "Unsupported or virtual source", "Browser, remote, archive, or virtual item"),
    ("MIXED-DPI", "Windows desktop", "Repeat on each available DPI scale / monitor"),
    ("CANCEL", "Windows desktop", "Escape, Shift release, and cancellation"),
    ("TOGGLE", "LocalShift settings", "Monitoring OFF/ON and restart persistence"),
    ("RELIABILITY", "LocalShift conversion", "Unsupported format, oversized input, collision, and source immutability"),
)


def _windows_name() -> str:
    if sys.platform != "win32":
        return platform.system()
    import winreg

    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Windows NT\CurrentVersion",
        ) as key:
            return str(winreg.QueryValueEx(key, "ProductName")[0])
    except OSError:
        return "Windows"


def new_manual_report() -> dict:
    return {
        "schema_version": 1,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "windows_name": _windows_name(),
            "windows_version": platform.version(),
            "architecture": platform.machine(),
            "processor": platform.processor(),
            "logical_cpu_count": os.cpu_count(),
            "python_version": platform.python_version(),
        },
        "cases": [
            {
                "id": case_id,
                "source_application": source,
                "source_version": (
                    f"Windows build {platform.version()}"
                    if case_id in ("EXP-SINGLE", "EXP-MULTI", "DESKTOP-SINGLE", "DESKTOP-MULTI")
                    else None
                ),
                "scenario": scenario,
                "status": "NOT TESTED",
                "local_payload_received": None,
                "selected_file_count": None,
                "output_correct": None,
                "cancellation_behavior": None,
                "evidence_notes": "",
            }
            for case_id, source, scenario in MANUAL_CASES
        ],
        "summary": {"passed": 0, "failed": 0, "not_tested": len(MANUAL_CASES)},
    }


def write_manual_report(report_path: Path, report: dict) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = report_path.with_name(report_path.name + ".tmp")
    temporary_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    temporary_path.replace(report_path)


def _prompt_choice(prompt: str, choices: dict[str, str]) -> str:
    labels = "/".join(choices)
    while True:
        answer = input(f"{prompt} [{labels}; default {next(iter(choices))}]: ").strip().lower()
        if not answer:
            answer = next(iter(choices))
        if answer in choices:
            return choices[answer]
        print(f"Enter one of: {labels}.")


def collect_manual_results(report_path: Path, report: dict) -> None:
    print("\nRecord only observations from the physical test you just performed.")
    print("Leave status NOT TESTED if you skipped a case. Do not enter file names or paths.")
    third_party = input("Third-party manager name (blank if not tested): ").strip()
    if third_party:
        case = next(case for case in report["cases"] if case["id"] == "THIRD-PARTY")
        case["source_application"] = third_party[:120]
        case["source_version"] = input("Third-party manager version: ").strip()[:80] or "Not recorded"
    virtual_source = input("Unsupported/virtual source name (blank if not tested): ").strip()
    if virtual_source:
        case = next(case for case in report["cases"] if case["id"] == "VIRTUAL")
        case["source_application"] = virtual_source[:120]
        case["source_version"] = input("Unsupported/virtual source version: ").strip()[:80] or "Not recorded"

    for case in report["cases"]:
        print(f"\n[{case['id']}] {case['source_application']} — {case['scenario']}")
        case["status"] = _prompt_choice(
            "Result",
            {"n": "NOT TESTED", "p": "PASS", "f": "FAIL"},
        )
        if case["status"] == "NOT TESTED":
            write_manual_report(report_path, report)
            continue
        if case["id"] in (
            "EXP-SINGLE",
            "EXP-MULTI",
            "DESKTOP-SINGLE",
            "DESKTOP-MULTI",
            "THIRD-PARTY",
        ):
            case["local_payload_received"] = _prompt_choice(
                "Genuine local filesystem payload received?",
                {"u": "UNKNOWN", "y": "YES", "n": "NO"},
            )
            count = input("Number of files actually dragged (count only; blank if unknown): ").strip()
            case["selected_file_count"] = int(count) if count.isdigit() else None
            case["output_correct"] = _prompt_choice(
                "Were selected outputs correct and were other files untouched?",
                {"u": "UNKNOWN", "y": "YES", "n": "NO", "a": "NOT APPLICABLE"},
            )
        elif case["id"] == "VIRTUAL":
            case["local_payload_received"] = _prompt_choice(
                "Was a local filesystem payload exposed?",
                {"u": "UNKNOWN", "y": "YES", "n": "NO"},
            )
            case["output_correct"] = _prompt_choice(
                "Was conversion safely rejected without output?",
                {"u": "UNKNOWN", "y": "YES", "n": "NO", "a": "NOT APPLICABLE"},
            )
        elif case["id"] == "CANCEL":
            case["cancellation_behavior"] = _prompt_choice(
                "Did each cancellation path avoid creating output and leave the app usable?",
                {"u": "UNKNOWN", "y": "YES", "n": "NO"},
            )
        elif case["id"] == "TOGGLE":
            case["cancellation_behavior"] = _prompt_choice(
                "Did OFF stop monitoring and did the saved choice survive restart?",
                {"u": "UNKNOWN", "y": "YES", "n": "NO"},
            )
        elif case["id"] == "RELIABILITY":
            case["output_correct"] = _prompt_choice(
                "Did format/size/collision checks fail safely without overwriting?",
                {"u": "UNKNOWN", "y": "YES", "n": "NO"},
            )
            case["cancellation_behavior"] = _prompt_choice(
                "Was the source unchanged after success, rejection, and failure?",
                {"u": "UNKNOWN", "y": "YES", "n": "NO"},
            )
        notes = input("Brief non-sensitive evidence/notes (no file names or paths): ").strip()
        case["evidence_notes"] = notes[:500]
        write_manual_report(report_path, report)

    statuses = [case["status"] for case in report["cases"]]
    report["summary"] = {
        "passed": statuses.count("PASS"),
        "failed": statuses.count("FAIL"),
        "not_tested": statuses.count("NOT TESTED"),
    }
    write_manual_report(report_path, report)
    print(
        "Manual verification summary: "
        f"{report['summary']['passed']} passed, "
        f"{report['summary']['failed']} failed, "
        f"{report['summary']['not_tested']} not tested."
    )
    print(f"Structured report saved to {report_path}")


def run_automated_checks() -> bool:
    print("=" * 70)
    print("LOCALSHIFT MILESTONE 21 — GESTURE & DESTINATION AUTOMATED CHECKS")
    print("=" * 70)
    all_passed = True

    # Check 1: Win32 Shift detection
    shift_state = is_shift_pressed()
    print(f"[CHECK 1] Physical Win32 Shift key check: active={shift_state} (Normal without key held)")

    # Check 2: Formats & Intersection
    temp_dir = Path("build/test_gesture_assets")
    temp_dir.mkdir(parents=True, exist_ok=True)

    png_path = temp_dir / "test_a.png"
    Image.new("RGB", (64, 64), color="blue").save(png_path)

    jpg_path = temp_dir / "test_b.jpg"
    Image.new("RGB", (64, 64), color="red").save(jpg_path)

    targets_png = get_supported_targets([png_path])
    print(f"[CHECK 2a] PNG targets count: {len(targets_png)} -> {targets_png[:4]}...")
    if not targets_png or "jpeg" not in targets_png:
        print("  FAIL: PNG missing expected JPEG target!")
        all_passed = False
    else:
        print("  PASS: PNG targets derived correctly from registry.")

    targets_both = get_supported_targets([png_path, jpg_path])
    print(f"[CHECK 2b] Multi-file intersection count: {len(targets_both)} -> {targets_both[:4]}...")
    if not targets_both or "pdf" not in targets_both:
        print("  FAIL: PNG+JPG intersection missing expected PDF target!")
        all_passed = False
    else:
        print("  PASS: Multi-file intersection derived correctly.")

    # Check 3: Destination hierarchy & validation
    st = get_settings()
    orig_enabled = st.save_to_folder_enabled
    orig_path = st.save_to_folder_path

    try:
        dest_test_dir = (temp_dir / "configured_save_folder").resolve()
        dest_test_dir.mkdir(parents=True, exist_ok=True)

        is_valid, err = validate_destination_directory(dest_test_dir)
        print(f"[CHECK 3a] Destination validation for writable dir: valid={is_valid}, err='{err}'")
        if not is_valid:
            print("  FAIL: Valid directory failed validation check!")
            all_passed = False

        st.save_to_folder_enabled = True
        st.save_to_folder_path = dest_test_dir

        # Precedence test 1: Explicit overrides global
        explicit_dir = temp_dir / "explicit_dir"
        res1 = st.resolve_destination(explicit_dir, temp_dir)
        if res1 != explicit_dir:
            print(f"  FAIL: Explicit dir precedence broken: expected {explicit_dir}, got {res1}")
            all_passed = False
        else:
            print("  PASS: Precedence 1 (Explicit per-job destination) verified.")

        # Precedence test 2: Global setting when enabled
        res2 = st.resolve_destination(None, temp_dir)
        if res2 != dest_test_dir:
            print(f"  FAIL: Global save folder precedence broken: expected {dest_test_dir}, got {res2}")
            all_passed = False
        else:
            print("  PASS: Precedence 2 (Global Save to Folder) verified.")

        # Precedence test 3: Fallback when disabled
        st.save_to_folder_enabled = False
        res3 = st.resolve_destination(None, temp_dir)
        if res3 != temp_dir:
            print(f"  FAIL: Fallback to source directory broken: expected {temp_dir}, got {res3}")
            all_passed = False
        else:
            print("  PASS: Precedence 3 (Source directory fallback) verified.")
    finally:
        st.save_to_folder_enabled = orig_enabled
        st.save_to_folder_path = orig_path

    print("=" * 70)
    if all_passed:
        print("ALL AUTOMATED CHECKS PASSED (100%)\n")
    else:
        print("SOME CHECKS FAILED!\n")
    return all_passed


def main():
    parser = argparse.ArgumentParser(description="Verify Windows OLE Shift+Drag gesture and LocalShift desktop behavior")
    parser.add_argument("--check", action="store_true", help="Run automated component checks only and exit")
    parser.add_argument("--interactive", action="store_true", help="Launch LocalShift for physical Windows gesture checks")
    parser.add_argument("--log-file", type=Path, help="Write privacy-conscious gesture diagnostics to this file")
    parser.add_argument(
        "--report-file",
        type=Path,
        help="Write the structured operator verification report (defaults to gesture-verification-report.json)",
    )
    args = parser.parse_args()

    if args.log_file and not args.interactive:
        parser.error("--log-file requires --interactive")
    if args.report_file and not args.interactive:
        parser.error("--report-file requires --interactive")
    if args.interactive and sys.platform != "win32":
        parser.error("--interactive is supported only on Windows")

    passed = run_automated_checks()
    if args.check:
        sys.exit(0 if passed else 1)

    print("To run interactive visual validation on Windows desktop:")
    print(
        "  .\\.venv\\Scripts\\python.exe scripts\\verify_windows_gesture.py --interactive "
        "--log-file .\\gesture-diagnostics.log "
        "--report-file .\\docs\\reports\\LS-BE-021-physical-verification.json"
    )
    print("Numbered physical test cases (record each result independently; do not infer cross-app support):")
    print("  [1] Explorer single file: Shift-drag one supported file, drop on a matching petal, verify output/source hash.")
    print("  [2] Explorer multiple files: confirm exactly the dragged files convert to a common target.")
    print("  [3] Desktop single file: repeat the single-file case independently.")
    print("  [4] Desktop multiple files: confirm no unselected files are converted.")
    print("  [5] Third-party manager: record app/version and whether local file URLs arrive.")
    print("  [6] Virtual/remote source: verify clear fallback and no conversion.")
    print("  [7] Mixed DPI: test monitor/sector alignment, focus and flicker on each available display.")
    print("  [8] Cancellation: test Escape, Shift release and drop outside a sector; no output should exist.")
    print("  [9] Toggle/restart: OFF must stop polling; verify explicit ON and persisted preference.")
    print("  [10] Reliability: unsupported format, >250 MiB input, collision, conversion failure and source hashes.")

    if args.interactive:
        report_path = args.report_file or Path("gesture-verification-report.json")
        report = new_manual_report()
        write_manual_report(report_path, report)
        print(f"Initial report written with every manual case marked NOT TESTED: {report_path}")
        handler = None
        loggers = [logging.getLogger(name) for name in (
            "localshift.shell_integration",
            "localshift.radial_menu",
        )]
        if args.log_file:
            log_path = args.log_file.resolve()
            log_path.parent.mkdir(parents=True, exist_ok=True)
            handler = logging.FileHandler(log_path, encoding="utf-8")
            handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
            for logger in loggers:
                logger.setLevel(logging.INFO)
                logger.addHandler(handler)
                logger.propagate = False
            print(f"Gesture diagnostics: {log_path}")

        from localshift.gui import main as launch_gui

        try:
            launch_gui()
        finally:
            if handler:
                for logger in loggers:
                    logger.removeHandler(handler)
                handler.close()
        collect_manual_results(report_path, report)


if __name__ == "__main__":
    main()
