"""Tests for privacy-safe physical gesture verification evidence."""

import hashlib
import json
import logging

import pytest

from scripts import verify_windows_gesture as verification
from scripts.verify_windows_gesture import (
    MANUAL_CASES,
    PrivacySafeGestureLogHandler,
    _run_gui_session,
    load_manual_report,
    new_manual_report,
    parse_safe_gesture_event,
    safe_relative_output_path,
    sha256_file,
    summarize_gesture_events,
    validate_jsonl_log,
    validate_report_destination,
    write_manual_report,
)


def test_manual_cases_are_unverified_until_operator_records_results():
    report = new_manual_report()

    assert len(report["cases"]) == len(MANUAL_CASES)
    assert report["schema_version"] == 2
    assert [case["id"] for case in report["cases"]] == [case[0] for case in MANUAL_CASES]
    assert all(case["status"] == "NOT TESTED" for case in report["cases"])
    assert all(case["operator_confirmed"] is False for case in report["cases"])
    assert report["summary"] == {
        "passed": 0,
        "failed": 0,
        "not_tested": len(MANUAL_CASES),
    }
    ids = {case["id"] for case in report["cases"]}
    assert {
        "EXP-SINGLE", "EXP-MULTI", "RADIAL-SINGLE", "RADIAL-MULTI",
        "CANCEL", "CANCEL-OUTSIDE", "REPEAT-WHEEL", "BUSY-CONVERSION", "MISSING-SOURCE",
    } <= ids
    assert report["environment"]["localshift_version"]
    assert all(case["run_environment"]["windows_version"] for case in report["cases"])
    assert all(case["conversion_dispatched_exactly_once"] == "UNKNOWN" for case in report["cases"])


def test_manual_report_writes_structured_json_atomically(tmp_path):
    report = new_manual_report()
    report_path = tmp_path / "gesture-report.json"

    write_manual_report(report_path, report)

    import json

    saved = json.loads(report_path.read_text(encoding="utf-8"))
    assert saved["schema_version"] == 2
    assert saved["cases"][0]["status"] == "NOT TESTED"
    assert list(tmp_path.iterdir()) == [report_path]


def test_unconfirmed_case_remains_not_tested(tmp_path, monkeypatch):
    report_path = tmp_path / "report.json"
    report = new_manual_report()
    case = report["cases"][0]
    monkeypatch.setattr("builtins.input", lambda _prompt: "")

    verification.collect_manual_results(report_path, report, case)

    saved = json.loads(report_path.read_text(encoding="utf-8"))
    assert saved["cases"][0]["operator_confirmed"] is False
    assert saved["cases"][0]["case_performed"] == "NO"
    assert saved["cases"][0]["status"] == "NOT TESTED"


def test_operator_observations_are_saved_only_from_explicit_answers(tmp_path, monkeypatch):
    report_path = tmp_path / "report.json"
    report = new_manual_report()
    case = report["cases"][0]
    case["source_sha256_before"] = ["abc"]
    case["source_sha256_after"] = ["abc"]
    answers = iter([
        "y", "2", "1", "c", "y", "n", "a", "n", "a", "y",
        "No freeze or ghost observed.", "outputs/case-01/result-01.pdf", "",
        "y", "y", "y", "p",
    ])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))

    verification.collect_manual_results(report_path, report, case)

    saved = json.loads(report_path.read_text(encoding="utf-8"))["cases"][0]
    assert saved["local_payload_received"] == "YES"
    assert saved["selected_file_count"] == 2
    assert saved["conversion_dispatch_count"] == 1
    assert saved["conversion_dispatched_exactly_once"] is True
    assert saved["drag_image_persisted_after_release"] == "NO"
    assert saved["ui_responsive"] == "RESPONSIVE"
    assert saved["source_unchanged"] is True
    assert saved["case_performed"] == "YES"
    assert saved["status"] == "PASS"
    assert saved["operator_recorded_utc"]


def test_operator_notes_reject_paths_and_accept_short_observation(monkeypatch):
    answers = iter([r"Error at C:\private\source.png", "OLE image remained after cancel"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))

    assert verification._prompt_notes() == "OLE image remained after cancel"


def test_legacy_report_migrates_without_losing_operator_status(tmp_path):
    report_path = tmp_path / "legacy.json"
    report = new_manual_report()
    report["schema_version"] = 1
    case = report["cases"][0]
    case["status"] = "PASS"
    case["evidence_notes"] = "Previously recorded evidence"
    for key in ("case_id", "operator_confirmed", "session_id", "observed_events"):
        case.pop(key)
    report_path.write_text(json.dumps(report), encoding="utf-8")

    migrated = load_manual_report(report_path)

    assert migrated["schema_version"] == 2
    assert migrated["cases"][0]["case_id"] == case["id"]
    assert migrated["cases"][0]["status"] == "PASS"
    assert migrated["cases"][0]["evidence_notes"] == "Previously recorded evidence"
    assert migrated["cases"][0]["operator_confirmed"] is False


def test_interactive_runner_refuses_to_overwrite_legacy_report(tmp_path):
    report_path = tmp_path / "legacy.json"
    report_path.write_text('{"schema_version":1,"cases":[]}', encoding="utf-8")
    original = report_path.read_bytes()

    with pytest.raises(ValueError, match="new v2 report path"):
        validate_report_destination(report_path)

    assert report_path.read_bytes() == original


def test_event_parser_keeps_only_allowlisted_gesture_fields():
    assert parse_safe_gesture_event(
        "localshift.radial_menu",
        "OLE drag accepted for preview: 2 local file(s), 4 target(s).",
        logging.INFO,
    ) == {"event": "payload_preview", "file_count": 2, "target_count": 4}
    assert parse_safe_gesture_event(
        "localshift.shell_integration",
        "Global OLE drop accepted: 1 file(s), target=docx.",
        logging.INFO,
    ) == {"event": "drop_accepted", "file_count": 1, "target_format": "docx"}
    assert parse_safe_gesture_event(
        "localshift.shell_integration",
        "Background gesture state: IDLE -> MENU_VISIBLE.",
        logging.INFO,
    ) == {
        "event": "state_transition",
        "from_state": "IDLE",
        "to_state": "MENU_VISIBLE",
    }

    private_message = r"Conversion failed for C:\Users\private\report.docx"
    safe_error = parse_safe_gesture_event("localshift.converter", private_message, logging.ERROR)
    assert safe_error == {"event": "application_diagnostic", "severity": "ERROR"}
    assert "private" not in json.dumps(safe_error)


def test_jsonl_handler_records_case_attributed_events_without_raw_messages(tmp_path):
    log_path = tmp_path / "gesture.jsonl"
    handler = PrivacySafeGestureLogHandler(log_path, "EXP-SINGLE")
    record = logging.LogRecord(
        "localshift.shell_integration",
        logging.INFO,
        "",
        0,
        "Global OLE drop accepted: %d file(s), target=%s.",
        (1, "docx"),
        None,
    )
    handler.emit(record)
    warning = logging.LogRecord(
        "localshift.converter",
        logging.WARNING,
        "",
        0,
        r"Input file not found: C:\Users\private\secret.docx",
        (),
        None,
    )
    handler.emit(warning)
    handler.close()

    lines = log_path.read_text(encoding="utf-8").splitlines()
    events = [json.loads(line) for line in lines]
    assert [event["case_id"] for event in events] == ["EXP-SINGLE", "EXP-SINGLE"]
    assert events[0]["event"] == "drop_accepted"
    assert events[1] == {
        "timestamp_utc": events[1]["timestamp_utc"],
        "case_id": "EXP-SINGLE",
        "event": "application_diagnostic",
        "severity": "WARNING",
    }
    assert "C:\\Users" not in log_path.read_text(encoding="utf-8")
    assert "secret.docx" not in log_path.read_text(encoding="utf-8")


def test_existing_plain_text_log_is_rejected_without_overwrite(tmp_path):
    log_path = tmp_path / "operator.log"
    original = "Existing user evidence; preserve unchanged."
    log_path.write_text(original, encoding="utf-8")

    with pytest.raises(ValueError, match="choose a new log path"):
        validate_jsonl_log(log_path)

    assert log_path.read_text(encoding="utf-8") == original


def test_event_summary_uses_only_observed_drop_and_terminal_events():
    summary = summarize_gesture_events(
        [
            {"event": "payload_preview", "file_count": 2},
            {"event": "drop_accepted", "file_count": 2, "target_format": "pdf"},
            {"event": "state_transition", "to_state": "COMPLETED"},
            {"event": "state_transition", "to_state": "IDLE"},
        ]
    )

    assert summary == {
        "payload_preview_file_counts": [2],
        "drop_payload_accepted": True,
        "accepted_drop_file_counts": [2],
        "observed_target_formats": ["pdf"],
        "observed_conversion_result": "COMPLETED",
    }


@pytest.mark.parametrize(
    ("raw_path", "expected"),
    [
        ("outputs/case-01/result-01.docx", "outputs/case-01/result-01.docx"),
        ("outputs\\case-02\\output-01.pdf", "outputs/case-02/output-01.pdf"),
    ],
)
def test_safe_relative_output_labels(raw_path, expected):
    assert safe_relative_output_path(raw_path) == expected


@pytest.mark.parametrize(
    "raw_path",
    [
        r"C:\Users\private\output.docx",
        r"\\server\share\output.docx",
        "/Users/private/output.docx",
        "outputs/../private.docx",
        "outputs/private-report.docx",
        "outputs",
    ],
)
def test_output_labels_reject_private_or_unsafe_paths(raw_path):
    with pytest.raises(ValueError):
        safe_relative_output_path(raw_path)


def test_sha256_helper_hashes_content_without_recording_source_path(tmp_path):
    source = tmp_path / "private-source.docx"
    source.write_bytes(b"synthetic fixture")
    expected_hash = hashlib.sha256(b"synthetic fixture").hexdigest()

    assert sha256_file(source) == expected_hash
    assert str(source) not in json.dumps(new_manual_report())


@pytest.mark.parametrize(("exit_code", "expected"), [(0, 0), (3, 3), ("error", 1)])
def test_gui_system_exit_is_captured_without_skipping_collection(exit_code, expected):
    def close_gui():
        raise SystemExit(exit_code)

    assert _run_gui_session(close_gui) == expected


def test_automated_checks_use_temporary_assets(monkeypatch, tmp_path):
    class SettingsStub:
        save_to_folder_enabled = False
        save_to_folder_path = None

        def resolve_destination(self, explicit, source):
            if explicit is not None:
                return explicit
            return self.save_to_folder_path if self.save_to_folder_enabled else source

    settings = SettingsStub()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(verification, "get_settings", lambda: settings)

    assert verification.run_automated_checks()
    assert not (tmp_path / "build").exists()
