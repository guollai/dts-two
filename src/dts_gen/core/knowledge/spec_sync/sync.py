from __future__ import annotations

from pathlib import Path

from dts_gen.core.knowledge.spec_sync.cache import read_cached, rotate_and_write, write_sync_meta
from dts_gen.core.knowledge.spec_sync.diff_report import DiffReport, build_diff_report
from dts_gen.core.knowledge.spec_sync.fetcher import FetchError, TrackedFile, fetch, list_rst_files

KERNEL_BINDING_FILES: list[TrackedFile] = [
    TrackedFile(
        "regulator.yaml",
        "https://raw.githubusercontent.com/torvalds/linux/master/Documentation/devicetree/bindings/regulator/regulator.yaml",
    ),
    TrackedFile(
        "gpio.txt",
        "https://raw.githubusercontent.com/torvalds/linux/master/Documentation/devicetree/bindings/gpio/gpio.txt",
    ),
    TrackedFile(
        "phy-bindings.txt",
        "https://raw.githubusercontent.com/torvalds/linux/master/Documentation/devicetree/bindings/phy/phy-bindings.txt",
    ),
]

DT_SPEC_CONTENTS_API_URL = "https://api.github.com/repos/devicetree-org/devicetree-specification/contents/source"


def spec_sync_cache_dir(base_dir: Path) -> Path:
    return base_dir / "knowledge" / "data" / "dt_spec"


def sync_bindings(cache_dir: Path) -> list[DiffReport]:
    try:
        dt_spec_files = list_rst_files(DT_SPEC_CONTENTS_API_URL)
        directory_error: DiffReport | None = None
    except FetchError as exc:
        dt_spec_files = []
        directory_error = DiffReport(filename="devicetree-specification/source", fetch_error=str(exc))

    reports: list[DiffReport] = []
    for entry in [*KERNEL_BINDING_FILES, *dt_spec_files]:
        try:
            new_text = fetch(entry.source_url)
        except FetchError as exc:
            reports.append(DiffReport(filename=entry.filename, fetch_error=str(exc)))
            continue

        old_text = read_cached(cache_dir, entry.filename, "latest")
        rotate_and_write(cache_dir, entry.filename, new_text)
        write_sync_meta(cache_dir, entry.filename, source_url=entry.source_url)

        reports.append(build_diff_report(old_text, new_text, entry.filename))

    if directory_error is not None:
        reports.append(directory_error)
    return reports
