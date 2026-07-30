from dts_gen.core.ir.models import HardwareIR, UnresolvedItem
from dts_gen.core.pipeline.explainer import explain_node


def test_explain_node_returns_matching_unresolved_item():
    ir = HardwareIR(
        unresolved=[UnresolvedItem(field="&usb_0", reason="连线不清晰", page=12)]
    )

    result = explain_node(ir, node_path="&usb_0")

    assert result.source_refs == []
    assert result.rule_ids == []
    assert len(result.unresolved) == 1
    assert result.unresolved[0].reason == "连线不清晰"


def test_explain_node_returns_empty_unresolved_when_no_match():
    ir = HardwareIR(unresolved=[UnresolvedItem(field="&usb_1", reason="不相关", page=1)])

    result = explain_node(ir, node_path="&usb_0")

    assert result.unresolved == []
