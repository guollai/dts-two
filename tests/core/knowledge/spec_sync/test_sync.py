from pathlib import Path
from unittest.mock import patch

from dts_gen.core.knowledge.spec_sync.fetcher import FetchError, TrackedFile
from dts_gen.core.knowledge.spec_sync.sync import KERNEL_BINDING_FILES, sync_bindings


def test_sync_bindings_first_run_marks_all_files_as_first_sync(tmp_path: Path):
    reports = sync_bindings(tmp_path)

    kernel_reports = [r for r in reports if r.filename in {f.filename for f in KERNEL_BINDING_FILES}]
    assert len(kernel_reports) == len(KERNEL_BINDING_FILES)
    assert all(r.first_sync for r in kernel_reports)
    assert any(r.filename.endswith(".rst") for r in reports)


def test_sync_bindings_second_run_detects_no_changes_for_stable_files(tmp_path: Path):
    sync_bindings(tmp_path)
    second_reports = sync_bindings(tmp_path)

    kernel_reports = [
        r for r in second_reports if r.filename in {f.filename for f in KERNEL_BINDING_FILES}
    ]
    assert all(not r.first_sync for r in kernel_reports)
    # Real upstream files might change between the two calls in rare cases,
    # but fetch_error must never be set for a successful second run.
    assert all(r.fetch_error is None for r in kernel_reports)


def test_sync_bindings_isolates_single_file_fetch_failure(tmp_path: Path):
    broken_file = TrackedFile(filename="broken.txt", source_url="https://raw.githubusercontent.com/does-not-exist/does-not-exist/main/nope.txt")

    with patch(
        "dts_gen.core.knowledge.spec_sync.sync.KERNEL_BINDING_FILES",
        [*KERNEL_BINDING_FILES, broken_file],
    ):
        reports = sync_bindings(tmp_path)

    broken_report = next(r for r in reports if r.filename == "broken.txt")
    assert broken_report.fetch_error is not None

    other_reports = [r for r in reports if r.filename != "broken.txt" and r.filename in {f.filename for f in KERNEL_BINDING_FILES}]
    assert all(r.fetch_error is None for r in other_reports)


def test_sync_bindings_falls_back_to_kernel_files_when_directory_listing_fails(tmp_path: Path):
    with patch(
        "dts_gen.core.knowledge.spec_sync.sync.DT_SPEC_CONTENTS_API_URL",
        "https://api.github.com/repos/does-not-exist/does-not-exist/contents/source",
    ):
        reports = sync_bindings(tmp_path)

    kernel_reports = [r for r in reports if r.filename in {f.filename for f in KERNEL_BINDING_FILES}]
    assert len(kernel_reports) == len(KERNEL_BINDING_FILES)
    assert all(r.fetch_error is None for r in kernel_reports)

    directory_failure = [r for r in reports if r.filename == "devicetree-specification/source"]
    assert len(directory_failure) == 1
    assert directory_failure[0].fetch_error is not None
