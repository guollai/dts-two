from pathlib import Path

import pytest

from dts_gen.core.ir.models import Component, HardwareIR, Relation
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


def test_identify_soc_mapping_returns_precondition_error_without_extraction(ctx, tmp_path: Path):
    pdf_path = tmp_path / "schematic.pdf"
    make_minimal_pdf(pdf_path, pages=1)
    created = tools.ingest_input(ctx, files=[{"path": str(pdf_path), "type": "pdf"}], project="p")

    result = tools.identify_soc_mapping(ctx, task_id=created["task_id"], soc="sa8775p")

    assert result["error"] == "precondition_failed"
    assert result["missing"] == "ir_ref"


def test_validate_dts_returns_precondition_error_without_generation(ctx, tmp_path: Path):
    pdf_path = tmp_path / "schematic.pdf"
    make_minimal_pdf(pdf_path, pages=1)
    created = tools.ingest_input(ctx, files=[{"path": str(pdf_path), "type": "pdf"}], project="p")
    task_id = created["task_id"]
    tools.extract_hardware_graph(ctx, task_id=task_id)

    result = tools.validate_dts(ctx, task_id=task_id)

    assert result["error"] == "precondition_failed"
    assert result["missing"] == "dts_ref"


def test_diff_dts_returns_precondition_error_without_generation(ctx, tmp_path: Path):
    pdf_path = tmp_path / "schematic.pdf"
    make_minimal_pdf(pdf_path, pages=1)
    created = tools.ingest_input(ctx, files=[{"path": str(pdf_path), "type": "pdf"}], project="p")
    task_id = created["task_id"]

    existing = tmp_path / "board.dts"
    existing.write_text("&usb_0 { status = \"disabled\"; };\n", encoding="utf-8")

    result = tools.diff_dts(ctx, task_id=task_id, existing_dts_path=str(existing))

    assert result["error"] == "precondition_failed"
    assert result["missing"] == "dts_ref"


def test_explain_node_returns_precondition_error_without_extraction(ctx, tmp_path: Path):
    pdf_path = tmp_path / "schematic.pdf"
    make_minimal_pdf(pdf_path, pages=1)
    created = tools.ingest_input(ctx, files=[{"path": str(pdf_path), "type": "pdf"}], project="p")

    result = tools.explain_node(ctx, task_id=created["task_id"], node_path="&usb_0")

    assert result["error"] == "precondition_failed"
    assert result["missing"] == "ir_ref"


def test_ingest_input_returns_file_not_found_for_missing_file(ctx, tmp_path: Path):
    missing_path = tmp_path / "does-not-exist.pdf"

    result = tools.ingest_input(
        ctx, files=[{"path": str(missing_path), "type": "pdf"}], project="p"
    )

    assert result["error"] == "file_not_found"


def test_diff_dts_returns_file_not_found_for_missing_existing_dts(ctx, tmp_path: Path):
    pdf_path = tmp_path / "schematic.pdf"
    make_minimal_pdf(pdf_path, pages=1)
    created = tools.ingest_input(ctx, files=[{"path": str(pdf_path), "type": "pdf"}], project="p")
    task_id = created["task_id"]
    tools.extract_hardware_graph(ctx, task_id=task_id)
    tools.generate_dts(ctx, task_id=task_id)

    missing_existing = tmp_path / "does-not-exist.dts"

    result = tools.diff_dts(ctx, task_id=task_id, existing_dts_path=str(missing_existing))

    assert result["error"] == "file_not_found"


def test_unhandled_exception_is_converted_to_internal_error_and_marks_task_failed(
    ctx, tmp_path: Path
):
    pdf_path = tmp_path / "schematic.pdf"
    make_minimal_pdf(pdf_path, pages=1)
    created = tools.ingest_input(ctx, files=[{"path": str(pdf_path), "type": "pdf"}], project="p")
    task_id = created["task_id"]
    extracted = tools.extract_hardware_graph(ctx, task_id=task_id)
    ir_ref = extracted["ir_ref"]

    # Corrupt the persisted IR file so that IrStore.load() raises a
    # pydantic ValidationError deep inside identify_soc_mapping, which no
    # existing code path catches.
    ir_path = tmp_path / task_id / ir_ref
    ir_path.write_text("not valid json {{{", encoding="utf-8")

    result = tools.identify_soc_mapping(ctx, task_id=task_id, soc="sa8775p")

    assert result["task_id"] == task_id
    assert result["error"] == "internal_error"
    assert isinstance(result["hint"], str) and result["hint"]

    task = ctx.task_store.get(task_id)
    assert task.status == "failed"


def test_extract_hardware_graph_persists_unresolved_items_into_ir(ctx, tmp_path: Path):
    pdf_path = tmp_path / "schematic.pdf"
    make_minimal_pdf(pdf_path, pages=1)
    created = tools.ingest_input(ctx, files=[{"path": str(pdf_path), "type": "pdf"}], project="p")
    task_id = created["task_id"]

    result = tools.extract_hardware_graph(ctx, task_id=task_id)

    assert len(result["unresolved"]) == 1
    persisted_ir = ctx.ir_store.load(task_id, result["ir_ref"])
    assert len(persisted_ir.unresolved) == 1
    assert persisted_ir.unresolved[0].field == result["unresolved"][0]["field"]
    assert persisted_ir.unresolved[0].reason == result["unresolved"][0]["reason"]


def test_explain_node_finds_extraction_unresolved_marker_without_mapping(ctx, tmp_path: Path):
    pdf_path = tmp_path / "schematic.pdf"
    make_minimal_pdf(pdf_path, pages=1)
    created = tools.ingest_input(ctx, files=[{"path": str(pdf_path), "type": "pdf"}], project="p")
    task_id = created["task_id"]
    tools.extract_hardware_graph(ctx, task_id=task_id)

    result = tools.explain_node(ctx, task_id=task_id, node_path="*")

    assert len(result["unresolved"]) == 1
    assert "not implemented" in result["unresolved"][0]["reason"].lower()


def test_generate_dts_includes_unresolved_field_in_output(ctx, tmp_path: Path):
    pdf_path = tmp_path / "schematic.pdf"
    make_minimal_pdf(pdf_path, pages=1)
    created = tools.ingest_input(ctx, files=[{"path": str(pdf_path), "type": "pdf"}], project="p")
    task_id = created["task_id"]
    tools.extract_hardware_graph(ctx, task_id=task_id)

    result = tools.generate_dts(ctx, task_id=task_id)

    assert "unresolved" in result
    assert result["unresolved"] == []


def test_generate_dts_reports_unresolved_relation_targets(ctx, tmp_path: Path):
    pdf_path = tmp_path / "schematic.pdf"
    make_minimal_pdf(pdf_path, pages=1)
    created = tools.ingest_input(ctx, files=[{"path": str(pdf_path), "type": "pdf"}], project="p")
    task_id = created["task_id"]

    ir = HardwareIR(
        components=[Component(id="pmic_ldo3", type="regulator", name="ldo3")],
        relations=[Relation(kind="supply", from_="pmic_ldo3", to="usb_ctrl0", property="vbus-supply")],
    )
    ctx.ir_store.save(task_id, ir)
    task = ctx.task_store.get(task_id)
    task.ir_ref = ctx.ir_store.latest_ref(task_id)
    task.status = "extracted"
    ctx.task_store.save(task)

    result = tools.generate_dts(ctx, task_id=task_id)

    assert len(result["unresolved"]) == 1


def test_sync_bindings_returns_reports_list_without_task_id(ctx):
    result = tools.sync_bindings(ctx)

    assert "task_id" not in result
    assert "reports" in result
    assert isinstance(result["reports"], list)
    assert len(result["reports"]) > 0
