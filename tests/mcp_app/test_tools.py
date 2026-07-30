from pathlib import Path

import pytest

from dts_gen.mcp_app import tools
from tests.fixtures.make_pdf import make_minimal_pdf


@pytest.fixture()
def ctx(tmp_path: Path):
    return tools.build_tool_context(base_dir=tmp_path)


def test_ingest_input_creates_task_and_returns_page_count(ctx, tmp_path: Path):
    pdf_path = tmp_path / "schematic.pdf"
    make_minimal_pdf(pdf_path, pages=2)

    result = tools.ingest_input(
        ctx, files=[{"path": str(pdf_path), "type": "pdf"}], project="p", soc="sa8775p"
    )

    assert result["status"] == "created"
    assert "task_id" in result
    assert result["input_summary"] == [{"path": str(pdf_path), "pages": 2}]


def test_extract_hardware_graph_requires_existing_task(ctx):
    result = tools.extract_hardware_graph(ctx, task_id="does-not-exist")

    assert result["error"] == "task_not_found"


def test_extract_hardware_graph_transitions_to_extracted(ctx, tmp_path: Path):
    pdf_path = tmp_path / "schematic.pdf"
    make_minimal_pdf(pdf_path, pages=1)
    created = tools.ingest_input(ctx, files=[{"path": str(pdf_path), "type": "pdf"}], project="p")
    task_id = created["task_id"]

    result = tools.extract_hardware_graph(ctx, task_id=task_id)

    assert result["status"] == "extracted"
    assert result["ir_ref"] == "ir/v1.json"
    assert result["summary"] == {"components": 0, "nets": 0, "relations": 0}
    assert len(result["unresolved"]) == 1


def test_generate_dts_returns_precondition_error_without_extraction(ctx, tmp_path: Path):
    pdf_path = tmp_path / "schematic.pdf"
    make_minimal_pdf(pdf_path, pages=1)
    created = tools.ingest_input(ctx, files=[{"path": str(pdf_path), "type": "pdf"}], project="p")

    result = tools.generate_dts(ctx, task_id=created["task_id"])

    assert result["error"] == "precondition_failed"
    assert result["missing"] == "ir_ref"


def test_full_happy_path_through_validate(ctx, tmp_path: Path):
    pdf_path = tmp_path / "schematic.pdf"
    make_minimal_pdf(pdf_path, pages=1)
    created = tools.ingest_input(ctx, files=[{"path": str(pdf_path), "type": "pdf"}], project="p")
    task_id = created["task_id"]

    tools.extract_hardware_graph(ctx, task_id=task_id)
    tools.identify_soc_mapping(ctx, task_id=task_id, soc="sa8775p")
    generated = tools.generate_dts(ctx, task_id=task_id)
    assert generated["status"] == "generated"
    assert generated["dts_ref"] == "dts/v1.dts"

    validated = tools.validate_dts(ctx, task_id=task_id)
    assert validated["status"] == "validated"
    assert validated["errors"] == []
    assert len(validated["warnings"]) == 1


def test_repair_dts_requires_dts_ref(ctx, tmp_path: Path):
    pdf_path = tmp_path / "schematic.pdf"
    make_minimal_pdf(pdf_path, pages=1)
    created = tools.ingest_input(ctx, files=[{"path": str(pdf_path), "type": "pdf"}], project="p")

    result = tools.repair_dts(ctx, task_id=created["task_id"])

    assert result["error"] == "precondition_failed"
    assert result["missing"] == "dts_ref"


def test_diff_dts_returns_patch_against_existing_file(ctx, tmp_path: Path):
    pdf_path = tmp_path / "schematic.pdf"
    make_minimal_pdf(pdf_path, pages=1)
    created = tools.ingest_input(ctx, files=[{"path": str(pdf_path), "type": "pdf"}], project="p")
    task_id = created["task_id"]
    tools.extract_hardware_graph(ctx, task_id=task_id)
    tools.generate_dts(ctx, task_id=task_id)

    existing = tmp_path / "board.dts"
    existing.write_text("&usb_0 { status = \"disabled\"; };\n", encoding="utf-8")

    result = tools.diff_dts(ctx, task_id=task_id, existing_dts_path=str(existing))

    assert "patch" in result
    assert result["risk_notes"] == []


def test_explain_node_returns_empty_when_no_unresolved_match(ctx, tmp_path: Path):
    pdf_path = tmp_path / "schematic.pdf"
    make_minimal_pdf(pdf_path, pages=1)
    created = tools.ingest_input(ctx, files=[{"path": str(pdf_path), "type": "pdf"}], project="p")
    task_id = created["task_id"]
    tools.extract_hardware_graph(ctx, task_id=task_id)

    result = tools.explain_node(ctx, task_id=task_id, node_path="&usb_0")

    assert result["source_refs"] == []
    assert result["rule_ids"] == []
