import sys
from pathlib import Path
from unittest.mock import patch

from dts_gen.cli import main


def test_main_with_no_args_runs_mcp_server():
    with patch("dts_gen.cli.run_server") as mock_run_server:
        with patch.object(sys, "argv", ["dts-gen"]):
            main()

    mock_run_server.assert_called_once()


def test_main_with_sync_bindings_arg_calls_sync_and_prints_reports(tmp_path: Path, capsys):
    from dts_gen.core.knowledge.spec_sync.diff_report import DiffReport

    fake_reports = [
        DiffReport(filename="gpio.txt", first_sync=True),
        DiffReport(filename="regulator.yaml", has_changes=True, diff="--- a\n+++ b"),
        DiffReport(filename="phy-bindings.txt", has_changes=False),
        DiffReport(filename="broken.txt", fetch_error="HTTP 404"),
    ]

    with patch("dts_gen.cli.run_sync_bindings", return_value=fake_reports) as mock_sync:
        with patch.object(sys, "argv", ["dts-gen", "sync-bindings"]):
            main()

    mock_sync.assert_called_once()
    captured = capsys.readouterr()
    assert "gpio.txt" in captured.out
    assert "首次同步" in captured.out
    assert "regulator.yaml" in captured.out
    assert "phy-bindings.txt" in captured.out
    assert "无变化" in captured.out
    assert "broken.txt" in captured.out
    assert "HTTP 404" in captured.out
