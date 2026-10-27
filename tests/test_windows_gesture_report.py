"""Tests for the privacy-conscious physical gesture verification report."""

from scripts.verify_windows_gesture import MANUAL_CASES, new_manual_report, write_manual_report


def test_manual_cases_are_unverified_until_operator_records_results():
    report = new_manual_report()

    assert len(report["cases"]) == len(MANUAL_CASES)
    assert [case["id"] for case in report["cases"]] == [case[0] for case in MANUAL_CASES]
    assert all(case["status"] == "NOT TESTED" for case in report["cases"])
    assert report["summary"] == {
        "passed": 0,
        "failed": 0,
        "not_tested": len(MANUAL_CASES),
    }


def test_manual_report_writes_structured_json_atomically(tmp_path):
    report = new_manual_report()
    report_path = tmp_path / "gesture-report.json"

    write_manual_report(report_path, report)

    import json

    saved = json.loads(report_path.read_text(encoding="utf-8"))
    assert saved["schema_version"] == 1
    assert saved["cases"][0]["status"] == "NOT TESTED"
    assert list(tmp_path.iterdir()) == [report_path]
