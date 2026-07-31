from __future__ import annotations

import sys
from pathlib import Path

from dts_gen.core.knowledge.spec_sync.diff_report import DiffReport
from dts_gen.core.knowledge.spec_sync.sync import sync_bindings as run_sync_bindings
from dts_gen.mcp_app.server import main as run_server


def _print_report(report: DiffReport) -> None:
    if report.fetch_error is not None:
        print(f"{report.filename}: 拉取失败: {report.fetch_error}")
    elif report.first_sync:
        print(f"{report.filename}: 首次同步")
    elif report.has_changes:
        print(f"{report.filename}: 有变化")
        print(report.diff)
    else:
        print(f"{report.filename}: 无变化")


def _sync_bindings_command() -> None:
    cache_dir = Path.cwd() / ".dts-gen" / "knowledge" / "data" / "dt_spec"
    reports = run_sync_bindings(cache_dir)
    for report in reports:
        _print_report(report)


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "sync-bindings":
        _sync_bindings_command()
    else:
        run_server()


if __name__ == "__main__":
    main()
