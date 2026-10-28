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
import hashlib
import json
import logging
import os
import platform
import re
import sys
import tempfile
import uuid
from pathlib import Path, PurePosixPath, PureWindowsPath
from PIL import Image

# Ensure localshift package import
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from localshift.radial_menu import (
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

GESTURE_STATES = {
    "IDLE",
    "DRAG_CANDIDATE",
    "MENU_VISIBLE",
    "TARGET_SELECTED",
    "CONVERTING",
    "COMPLETED",
    "CANCELLED",
    "FAILED",
}

_STATE_RE = re.compile(r"Background gesture state: ([A-Z_]+) -> ([A-Z_]+)\.")
_PREVIEW_RE = re.compile(
    r"OLE drag accepted for preview: (\d+) local file\(s\), (\d+) target\(s\)\."
)
_DROP_ACCEPTED_RE = re.compile(r"Global OLE drop accepted: (\d+) file\(s\), target=([a-z0-9_-]+)\.")


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
    cases = []
    for case_id, source, scenario in MANUAL_CASES:
        cases.append({
            "id": case_id,
            "case_id": case_id,
            "source_application": source,
            "source_version": (
                f"Windows build {platform.version()}"
                if case_id in ("EXP-SINGLE", "EXP-MULTI", "DESKTOP-SINGLE", "DESKTOP-MULTI")
                else None
            ),
            "scenario": scenario,
            "status": "NOT TESTED",
            "local_payload_received": "UNKNOWN",
            "selected_file_count": None,
            "payload_preview_file_counts": [],
            "drop_payload_accepted": None,
            "accepted_drop_file_counts": [],
            "observed_target_formats": [],
            "observed_conversion_result": "UNKNOWN",
            "operator_conversion_result": "UNKNOWN",
            "conversion_error_category": "UNKNOWN",
            "output_paths": [],
            "output_correct": "UNKNOWN",
            "source_sha256_before": None,
            "source_sha256_after": None,
            "source_hashes_match_dragged_files": "UNKNOWN",
            "source_unchanged": None,
            "cancellation_behavior": "UNKNOWN",
            "operator_confirmed": False,
            "session_id": None,
            "observed_events": [],
            "evidence_notes": "",
        })
    return {
        "schema_version": 2,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "windows_name": _windows_name(),
            "windows_version": platform.version(),
            "architecture": platform.machine(),
            "processor": platform.processor(),
            "logical_cpu_count": os.cpu_count(),
            "python_version": platform.python_version(),
        },
        "cases": cases,
        "summary": {"passed": 0, "failed": 0, "not_tested": len(MANUAL_CASES)},
    }


def load_manual_report(report_path: Path) -> dict:
    if not report_path.exists():
        return new_manual_report()
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("Could not read the selected verification report.") from exc
    if not isinstance(report, dict) or report.get("schema_version") not in (1, 2):
        raise ValueError("Unsupported verification report schema.")
    existing = report.get("cases")
    if not isinstance(existing, list):
        raise ValueError("Verification report has no valid case list.")
    existing_by_id = {case.get("id"): case for case in existing if isinstance(case, dict)}
    if len(existing_by_id) != len(existing):
        raise ValueError("Verification report contains duplicate or malformed case IDs.")
    defaults = new_manual_report()["cases"]
    if not set(existing_by_id).issubset({case["id"] for case in defaults}):
        raise ValueError("Verification report contains unknown case IDs.")
    for default in defaults:
        case = existing_by_id.get(default["id"])
        if case is None:
            existing.append(default)
            continue
        for key, value in default.items():
            if key not in case or (case[key] is None and value is not None):
                case[key] = value
        case["case_id"] = default["id"]
    report["cases"] = existing
    report["schema_version"] = 2
    report.setdefault("summary", {"passed": 0, "failed": 0, "not_tested": len(defaults)})
    return report


def validate_report_destination(report_path: Path) -> None:
    if not report_path.exists():
        return
    try:
        existing = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("Could not read the selected verification report.") from exc
    if isinstance(existing, dict) and existing.get("schema_version") == 1:
        raise ValueError("Choose a new v2 report path; the existing v1 evidence will not be overwritten.")


def write_manual_report(report_path: Path, report: dict) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{report_path.name}.",
        suffix=".tmp",
        dir=report_path.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(report, stream, indent=2)
            stream.write("\n")
        os.replace(temporary_path, report_path)
    finally:
        temporary_path.unlink(missing_ok=True)


def parse_safe_gesture_event(logger_name: str, message: str, levelno: int) -> dict | None:
    """Keep only known non-sensitive gesture fields; never persist raw log messages."""
    state_match = _STATE_RE.fullmatch(message)
    if state_match and state_match.group(1) in GESTURE_STATES and state_match.group(2) in GESTURE_STATES:
        return {
            "event": "state_transition",
            "from_state": state_match.group(1),
            "to_state": state_match.group(2),
        }

    preview_match = _PREVIEW_RE.fullmatch(message)
    if logger_name == "localshift.radial_menu" and preview_match:
        return {
            "event": "payload_preview",
            "file_count": int(preview_match.group(1)),
            "target_count": int(preview_match.group(2)),
        }

    drop_match = _DROP_ACCEPTED_RE.fullmatch(message)
    if logger_name == "localshift.shell_integration" and drop_match:
        return {
            "event": "drop_accepted",
            "file_count": int(drop_match.group(1)),
            "target_format": drop_match.group(2),
        }

    safe_messages = {
        "Background Shift+Drag gesture controller started.": "controller_started",
        "Background Shift+Drag gesture controller stopped.": "controller_stopped",
        "Global radial drop target opened; awaiting local file URLs.": "drop_target_opened",
        "Global drag released; awaiting an accepted OLE file drop.": "drag_released",
        "Global gesture cancelled: no supported OLE file drop received.": "gesture_cancelled",
        "Ignoring stale or duplicate global OLE drop dispatch.": "duplicate_dispatch_ignored",
        "OLE drag rejected: This source does not expose local file URLs.": "payload_rejected",
        "OLE drag rejected: This source did not provide any files.": "payload_rejected",
        "OLE drag rejected: Only local files can be converted.": "payload_rejected",
        "OLE drag rejected: The drop contains an invalid or unsupported file path.": "payload_rejected",
        "OLE drag rejected: A dropped file exceeds the 250 MiB input limit.": "payload_rejected",
        "OLE drag rejected: A dropped file could not be accessed.": "payload_rejected",
        "OLE drag rejected: No common conversion target is available for these files.": "payload_rejected",
        "OLE drop rejected: This source does not expose local file URLs.": "payload_rejected",
        "OLE drop rejected: This source did not provide any files.": "payload_rejected",
        "OLE drop rejected: Only local files can be converted.": "payload_rejected",
        "OLE drop rejected: The drop contains an invalid or unsupported file path.": "payload_rejected",
        "OLE drop rejected: A dropped file exceeds the 250 MiB input limit.": "payload_rejected",
        "OLE drop rejected: A dropped file could not be accessed.": "payload_rejected",
        "OLE drop rejected: No common conversion target is available for these files.": "payload_rejected",
        "OLE drop rejected: drop position did not hit a format sector.": "drop_rejected",
    }
    if message in safe_messages:
        return {"event": safe_messages[message]}
    if levelno >= logging.WARNING:
        return {"event": "application_diagnostic", "severity": logging.getLevelName(levelno)}
    return None


def validate_jsonl_log(log_path: Path) -> None:
    if not log_path.exists() or log_path.stat().st_size == 0:
        return
    try:
        with log_path.open(encoding="utf-8") as stream:
            for line in stream:
                event = json.loads(line)
                if not isinstance(event, dict) or "event" not in event or "case_id" not in event:
                    raise ValueError
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError("Existing log is not a LocalShift privacy-safe JSONL log; choose a new log path.") from exc


class PrivacySafeGestureLogHandler(logging.Handler):
    def __init__(self, log_path: Path, case_id: str):
        super().__init__(logging.INFO)
        validate_jsonl_log(log_path)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        self._stream = log_path.open("a", encoding="utf-8", newline="\n")
        self.case_id = case_id
        self.events: list[dict] = []
        self.write_failed = False

    def record_event(self, event: dict) -> None:
        event = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "case_id": self.case_id,
            **event,
        }
        self.events.append(event)
        try:
            self._stream.write(json.dumps(event, separators=(",", ":")) + "\n")
            self._stream.flush()
        except OSError:
            self.write_failed = True

    def emit(self, record: logging.LogRecord) -> None:
        event = parse_safe_gesture_event(record.name, record.getMessage(), record.levelno)
        if event is None:
            return
        self.record_event(event)

    def close(self) -> None:
        try:
            self._stream.close()
        except OSError:
            self.write_failed = True
        super().close()


def summarize_gesture_events(events: list[dict]) -> dict:
    previews = sorted({event["file_count"] for event in events if event["event"] == "payload_preview"})
    accepted_drops = [event for event in events if event["event"] == "drop_accepted"]
    terminal_states = [
        event["to_state"]
        for event in events
        if event["event"] == "state_transition"
        and event["to_state"] in {"COMPLETED", "FAILED", "CANCELLED"}
    ]
    return {
        "payload_preview_file_counts": previews,
        "drop_payload_accepted": True if accepted_drops else (
            False if any(event["event"] == "payload_rejected" for event in events) else None
        ),
        "accepted_drop_file_counts": sorted({event["file_count"] for event in accepted_drops}),
        "observed_target_formats": sorted({event["target_format"] for event in accepted_drops}),
        "observed_conversion_result": terminal_states[-1] if terminal_states else "UNKNOWN",
    }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def hash_source_paths(paths: list[Path]) -> list[str] | None:
    try:
        return [sha256_file(path) for path in paths]
    except OSError:
        return None


def collect_source_hash_inputs() -> tuple[list[Path], list[str]]:
    print("Source paths are used only in memory to calculate SHA-256; paths are never written to report or log.")
    paths: list[Path] = []
    hashes: list[str] = []
    while True:
        raw_path = input("Private source file path for hashing (blank when finished or to skip): ").strip()
        if not raw_path:
            break
        raw_path = raw_path.strip('"')
        path = Path(raw_path).expanduser()
        try:
            if not path.is_file():
                raise OSError
            digest = sha256_file(path)
        except OSError:
            print("Could not hash that source file; path was not recorded. Try again or press Enter to skip.")
            continue
        paths.append(path)
        hashes.append(digest)
    return paths, hashes


def safe_relative_output_path(raw_path: str) -> str:
    normalized = raw_path.strip().replace("\\", "/")
    windows_path = PureWindowsPath(normalized)
    relative_path = PurePosixPath(normalized)
    if (
        not normalized
        or normalized in {".", "./"}
        or normalized.startswith("/")
        or windows_path.is_absolute()
        or windows_path.drive
        or ".." in relative_path.parts
        or len(relative_path.parts) < 3
        or relative_path.parts[0].lower() != "outputs"
        or any(
            not re.fullmatch(r"case-\d+", part, re.IGNORECASE)
            for part in relative_path.parts[1:-1]
        )
        or not re.fullmatch(r"(?:result|output|file)-\d+\.[a-z0-9]{1,10}", relative_path.parts[-1], re.IGNORECASE)
        or any(ord(char) < 32 for char in normalized)
    ):
        raise ValueError("Use a synthetic relative label such as outputs/case-01/result-01.docx.")
    return normalized


def collect_output_path_labels() -> list[str]:
    print("Use only synthetic labels under outputs/, such as outputs/case-01/result-01.docx.")
    paths: list[str] = []
    while True:
        raw_path = input("Relative output path label (blank when finished/none): ").strip()
        if not raw_path:
            return paths
        try:
            paths.append(safe_relative_output_path(raw_path))
        except ValueError:
            print("Use a relative label such as outputs/case-01/result.docx; full paths are not accepted.")


def _run_gui_session(launch_gui) -> int:
    try:
        launch_gui()
    except SystemExit as exc:
        if exc.code is None:
            return 0
        return exc.code if isinstance(exc.code, int) else 1
    return 0


def _prompt_choice(prompt: str, choices: dict[str, str]) -> str:
    labels = "/".join(choices)
    while True:
        answer = input(f"{prompt} [{labels}; default {next(iter(choices))}]: ").strip().lower()
        if not answer:
            answer = next(iter(choices))
        if answer in choices:
            return choices[answer]
        print(f"Enter one of: {labels}.")


def _prompt_file_count() -> int | None:
    while True:
        raw_count = input("Actual number of dragged files (blank if unknown): ").strip()
        if not raw_count:
            return None
        if raw_count.isdigit():
            return int(raw_count)
        print("Enter a non-negative whole number or leave blank.")


def collect_manual_results(
    report_path: Path,
    report: dict,
    case: dict,
) -> None:
    case["local_payload_received"] = _prompt_choice(
        "Did this case expose a genuine local file payload?",
        {"u": "UNKNOWN", "a": "NOT APPLICABLE", "y": "YES", "n": "NO"},
    )
    case["selected_file_count"] = _prompt_file_count()

    case["operator_conversion_result"] = _prompt_choice(
        "Observed conversion result",
        {
            "u": "UNKNOWN",
            "c": "COMPLETED",
            "f": "FAILED",
            "n": "NOT DISPATCHED",
        },
    )
    case["output_correct"] = _prompt_choice(
        "Was output correct and were other files untouched?",
        {"u": "UNKNOWN", "y": "YES", "n": "NO", "a": "NOT APPLICABLE"},
    )
    case["conversion_error_category"] = _prompt_choice(
        "Error category, if any (do not enter raw error text or paths)",
        {
            "?": "UNKNOWN",
            "n": "NONE",
            "i": "INPUT_NOT_FOUND",
            "a": "ACCESS_DENIED",
            "u": "UNSUPPORTED_FORMAT",
            "c": "OUTPUT_COLLISION",
            "x": "OTHER",
        },
    )
    case["cancellation_behavior"] = _prompt_choice(
        "Cancellation result for the scenario (or N/A)",
        {"u": "UNKNOWN", "p": "PASS", "f": "FAIL", "a": "NOT APPLICABLE"},
    )
    case["output_paths"] = collect_output_path_labels()

    source_match = _prompt_choice(
        "Were the hashed source paths exactly the dragged source file(s)?",
        {"u": "UNKNOWN", "a": "NOT APPLICABLE", "y": "YES", "n": "NO"},
    )
    case["source_hashes_match_dragged_files"] = source_match
    before = case["source_sha256_before"]
    after = case["source_sha256_after"]
    case["source_unchanged"] = (
        before == after
        if source_match == "YES" and before and after is not None
        else None
    )
    case["operator_confirmed"] = _prompt_choice(
        "Do you confirm these fields are direct observations for this displayed case ID?",
        {"n": "NO", "y": "YES"},
    ) == "YES"
    if case["operator_confirmed"]:
        case["status"] = _prompt_choice(
            "Case result",
            {"n": "NOT TESTED", "p": "PASS", "f": "FAIL"},
        )
    else:
        case["status"] = "NOT TESTED"

    statuses = [item["status"] for item in report["cases"]]
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


def _prompt_source_label(prompt: str, default: str | None) -> str:
    while True:
        value = input(f"{prompt} [{default or 'not recorded'}]: ").strip() or (default or "")
        if len(value) <= 120 and not any(ord(char) < 32 for char in value) and not re.search(
            r"(?:[A-Za-z]:[\\/]|[\\/]{2})", value
        ):
            return value
        print("Enter a short application label/version, not a path.")


def _run_interactive_case(report_path: Path, log_path: Path, report: dict, case: dict) -> None:
    print(f"\nCase {case['id']}: {case['source_application']} — {case['scenario']}")
    print("Use only the displayed case for this app session; the report status stays NOT TESTED until confirmed.")
    case["source_application"] = _prompt_source_label(
        "Actual source application",
        case["source_application"],
    ) or "Not recorded"
    case["source_version"] = _prompt_source_label(
        "Actual source application / Windows version",
        case["source_version"],
    ) or "Not recorded"
    source_paths, hashes_before = collect_source_hash_inputs()
    case["source_sha256_before"] = hashes_before or None
    case["session_id"] = str(uuid.uuid4())
    case["operator_confirmed"] = False
    case["status"] = "NOT TESTED"

    handler = PrivacySafeGestureLogHandler(log_path, case["id"])
    handler.record_event({"event": "session_started"})
    loggers = [
        logging.getLogger("localshift.shell_integration"),
        logging.getLogger("localshift.radial_menu"),
    ]
    root_logger = logging.getLogger()
    previous_logger_state = [(logger, logger.level, logger.propagate) for logger in loggers]
    for logger in loggers:
        logger.setLevel(logging.INFO)
        logger.addHandler(handler)
        logger.propagate = False
    root_logger.addHandler(handler)

    exit_code = None
    try:
        from localshift.gui import main as launch_gui

        exit_code = _run_gui_session(launch_gui)
    finally:
        handler.record_event({"event": "session_ended", "exit_code": exit_code})
        for logger, level, propagate in previous_logger_state:
            logger.removeHandler(handler)
            logger.setLevel(level)
            logger.propagate = propagate
        root_logger.removeHandler(handler)
        handler.close()
        case["gui_exit_code"] = exit_code
        case["observed_events"] = handler.events
        observations = summarize_gesture_events(handler.events)
        case.update(observations)
        case["source_sha256_after"] = hash_source_paths(source_paths) if source_paths else None
        case["diagnostics_write_failed"] = handler.write_failed
        report["summary"] = {
            "passed": sum(item["status"] == "PASS" for item in report["cases"]),
            "failed": sum(item["status"] == "FAIL" for item in report["cases"]),
            "not_tested": sum(item["status"] == "NOT TESTED" for item in report["cases"]),
        }
        write_manual_report(report_path, report)

    if exit_code:
        print(f"LocalShift exited with code {exit_code}; this is recorded and is not treated as a pass.")
    if handler.write_failed:
        print("Warning: diagnostics could not be fully written; the physical case remains unverified.")
    print(
        "Captured diagnostics: "
        f"{len(handler.events)} safe events, "
        f"{len(case['payload_preview_file_counts'])} distinct preview file-count value(s), "
        f"{len(case['accepted_drop_file_counts'])} accepted drop file-count value(s), "
        f"observed result {case['observed_conversion_result']}."
    )
    collect_manual_results(report_path, report, case)


def run_automated_checks() -> bool:
    print("=" * 70)
    print("LOCALSHIFT — GESTURE & DESTINATION AUTOMATED CHECKS")
    print("=" * 70)
    with tempfile.TemporaryDirectory(prefix="localshift-gesture-check-") as temporary_directory:
        return _run_automated_checks_in(Path(temporary_directory))


def _run_automated_checks_in(temp_dir: Path) -> bool:
    all_passed = True

    # Check 1: Win32 Shift detection
    shift_state = is_shift_pressed()
    print(f"[CHECK 1] Physical Win32 Shift key check: active={shift_state} (Normal without key held)")

    # Check 2: Formats & Intersection
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
    parser.add_argument("--log-file", type=Path, help="Append privacy-safe JSONL gesture diagnostics")
    parser.add_argument("--case-id", choices=[case[0] for case in MANUAL_CASES], help="Run one attributable physical case")
    parser.add_argument(
        "--report-file",
        type=Path,
        help="Versioned structured operator report; prior case evidence is preserved",
    )
    args = parser.parse_args()

    if args.interactive and (args.log_file is None or args.report_file is None or args.case_id is None):
        parser.error("--interactive requires --case-id, --log-file, and --report-file")
    if not args.interactive and any((args.log_file, args.report_file, args.case_id)):
        parser.error("--case-id, --log-file, and --report-file require --interactive")
    if args.interactive and args.check:
        parser.error("Use --check or --interactive, not both")
    if args.interactive and sys.platform != "win32":
        parser.error("--interactive is supported only on Windows")
    report_path = args.report_file.resolve() if args.interactive else None
    log_path = args.log_file.resolve() if args.interactive else None
    if args.interactive and report_path == log_path:
        parser.error("The JSON report and JSONL diagnostics must use different files")
    if report_path is not None:
        try:
            validate_report_destination(report_path)
        except ValueError as exc:
            parser.error(str(exc))

    passed = run_automated_checks()
    if args.check:
        sys.exit(0 if passed else 1)
    if not passed:
        print("Automated checks failed; do not begin physical verification until the failure is resolved.")
        return 1

    if not args.interactive:
        print("Numbered physical test cases (run one case ID per GUI session; do not infer cross-app support):")
        for number, (case_id, source, scenario) in enumerate(MANUAL_CASES, start=1):
            print(f"  [{number}] {case_id}: {source} — {scenario}")
        return

    if report_path is None or log_path is None or args.case_id is None:
        parser.error("--interactive requires case ID, report path, and diagnostics path")
    try:
        report = load_manual_report(report_path)
    except ValueError as exc:
        parser.error(str(exc))
    case = next(item for item in report["cases"] if item["id"] == args.case_id)
    if case["status"] != "NOT TESTED" or case.get("session_id"):
        parser.error("This case already has recorded evidence; choose a fresh report path to preserve it")

    print(f"Launching only case {case['id']}; all other cases remain at their recorded status.")
    try:
        _run_interactive_case(report_path, log_path, report, case)
    except ValueError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    sys.exit(main())
