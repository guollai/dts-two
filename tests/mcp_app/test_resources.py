from pathlib import Path

from dts_gen.mcp_app.resources import build_knowledge_context, read_binding, read_device, read_soc_dtsi, read_styleguide


def test_read_soc_dtsi_returns_empty_files_when_no_data(tmp_path: Path):
    ctx = build_knowledge_context(data_dir=tmp_path)

    result = read_soc_dtsi(ctx, soc="sa8775p")

    assert result == {"soc": "sa8775p", "files": []}


def test_read_binding_returns_not_found_when_missing(tmp_path: Path):
    ctx = build_knowledge_context(data_dir=tmp_path)

    result = read_binding(ctx, compatible="snps,dwc3")

    assert result == {"error": "not_found", "compatible": "snps,dwc3"}


def test_read_device_returns_not_found_when_missing(tmp_path: Path):
    ctx = build_knowledge_context(data_dir=tmp_path)

    result = read_device(ctx, part_number="tusb2e11")

    assert result == {"error": "not_found", "part_number": "tusb2e11"}


def test_read_styleguide_returns_empty_content_when_missing(tmp_path: Path):
    ctx = build_knowledge_context(data_dir=tmp_path)

    result = read_styleguide(ctx)

    assert result == {"content": ""}
