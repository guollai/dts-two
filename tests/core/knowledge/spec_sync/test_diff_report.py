from dts_gen.core.knowledge.spec_sync.diff_report import DiffReport, build_diff_report


def test_build_diff_report_marks_first_sync_when_no_previous_text():
    report = build_diff_report(None, "new content", "gpio.txt")

    assert report.first_sync is True
    assert report.has_changes is False
    assert report.diff is None


def test_build_diff_report_detects_no_changes_for_identical_text():
    report = build_diff_report("same content", "same content", "gpio.txt")

    assert report.has_changes is False
    assert report.diff is None
    assert report.first_sync is False


def test_build_diff_report_produces_unified_diff_for_changed_text():
    report = build_diff_report("line one\nline two\n", "line one\nline three\n", "gpio.txt")

    assert report.has_changes is True
    assert "line two" in report.diff
    assert "line three" in report.diff


def test_diff_report_defaults_fetch_error_to_none():
    report = DiffReport(filename="gpio.txt")

    assert report.fetch_error is None
    assert report.first_sync is False
