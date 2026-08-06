from dts_gen.core.pipeline.semantic_import import parse_connected_label, ImportResult, import_block_semantic


def test_parse_connected_label_extracts_designator_and_pin():
    assert parse_connected_label("R3 pin 1") == ("R3", "1")


def test_parse_connected_label_handles_alphanumeric_pin():
    assert parse_connected_label("SU1C pin G37") == ("SU1C", "G37")


def test_parse_connected_label_handles_no_space_before_pin_number():
    assert parse_connected_label("R544 pin2") == ("R544", "2")


def test_parse_connected_label_returns_none_for_single_bracket_reference():
    assert parse_connected_label("[22]") is None


def test_parse_connected_label_returns_none_for_multi_page_bracket_reference():
    assert parse_connected_label("[7,37,8]") is None


def test_parse_connected_label_returns_none_for_coordinate_bracket_reference():
    assert parse_connected_label("[47-C4,47-D4]") is None


def test_parse_connected_label_returns_none_for_bare_net_name():
    assert parse_connected_label("VDD_CX") is None


def test_parse_connected_label_returns_none_for_ground_label():
    assert parse_connected_label("GND") is None


def test_parse_connected_label_returns_none_for_uncertain_designator():
    assert parse_connected_label("C? pin 1") is None


def test_import_block_semantic_converts_components_with_designator_and_type():
    data = {
        "blocks": [
            {
                "blockId": "block_0003",
                "components": [
                    {"designator": "R3", "componentType": "resistor", "pinCount": 2},
                    {"designator": "R5", "componentType": "resistor", "pinCount": 2},
                ],
            }
        ]
    }

    result = import_block_semantic(data)

    assert isinstance(result, ImportResult)
    ids = {c.id for c in result.ir.components}
    assert ids == {"R3", "R5"}
    r3 = next(c for c in result.ir.components if c.id == "R3")
    assert r3.type == "resistor"
    assert r3.name == "R3"


def test_import_block_semantic_merges_components_across_multiple_blocks():
    data = {
        "blocks": [
            {"blockId": "block_0001", "components": [{"designator": "R3", "componentType": "resistor"}]},
            {"blockId": "block_0002", "components": [{"designator": "C1", "componentType": "capacitor"}]},
        ]
    }

    result = import_block_semantic(data)

    ids = {c.id for c in result.ir.components}
    assert ids == {"R3", "C1"}


def test_import_block_semantic_reports_unresolved_for_component_missing_designator():
    data = {
        "blocks": [
            {"blockId": "block_0001", "components": [{"componentType": "resistor"}]},
        ]
    }

    result = import_block_semantic(data)

    assert result.ir.components == []
    assert len(result.unresolved) == 1
    assert result.unresolved[0].field == "component:block_0001"


def test_import_block_semantic_reports_unresolved_for_component_missing_type():
    data = {
        "blocks": [
            {"blockId": "block_0001", "components": [{"designator": "R3"}]},
        ]
    }

    result = import_block_semantic(data)

    assert result.ir.components == []
    assert len(result.unresolved) == 1


def test_import_block_semantic_handles_missing_blocks_key():
    result = import_block_semantic({})

    assert result.ir.components == []
    assert result.unresolved == []


def test_import_block_semantic_handles_block_missing_components_key():
    data = {"blocks": [{"blockId": "block_0001"}]}

    result = import_block_semantic(data)

    assert result.ir.components == []


def test_import_block_semantic_builds_net_with_parsed_members():
    data = {
        "blocks": [
            {
                "blockId": "block_0003",
                "nets": [
                    {"netNameLabel": "PCIE4_REFCLK_100M+", "connectedLabels": ["R3 pin 1", "R5 pin 1"]},
                ],
                "components": [
                    {"designator": "R3", "componentType": "resistor"},
                    {"designator": "R5", "componentType": "resistor"},
                ],
            }
        ]
    }

    result = import_block_semantic(data)

    assert len(result.ir.nets) == 1
    net = result.ir.nets[0]
    assert net.name == "PCIE4_REFCLK_100M+"
    assert net.members == ["R3:1", "R5:1"]


def test_import_block_semantic_skips_bare_net_name_self_reference():
    data = {
        "blocks": [
            {
                "blockId": "block_0003",
                "nets": [
                    {"netNameLabel": "PCIE4_REFCLK_100M+", "connectedLabels": ["PCIE4_REFCLK_100M+", "R3 pin 1"]},
                ],
                "components": [{"designator": "R3", "componentType": "resistor"}],
            }
        ]
    }

    result = import_block_semantic(data)

    assert result.ir.nets[0].members == ["R3:1"]
    assert result.unresolved == []


def test_import_block_semantic_skips_bracket_reference_without_unresolved():
    data = {
        "blocks": [
            {
                "blockId": "block_0003",
                "nets": [
                    {"netNameLabel": "DOCK_VDM_PWR_ON", "connectedLabels": ["SQ17 pin 1", "[5]"]},
                ],
                "components": [{"designator": "SQ17", "componentType": "transistor"}],
            }
        ]
    }

    result = import_block_semantic(data)

    assert result.ir.nets[0].members == ["SQ17:1"]
    assert result.unresolved == []


def test_import_block_semantic_reports_unresolved_for_uncertain_pin_label():
    data = {
        "blocks": [
            {
                "blockId": "block_0003",
                "nets": [
                    {"netNameLabel": None, "connectedLabels": ["C? pin 1"]},
                ],
            }
        ]
    }

    result = import_block_semantic(data)

    assert result.ir.nets[0].members == []
    assert len(result.unresolved) == 1
    assert "C? pin 1" in result.unresolved[0].reason


def test_import_block_semantic_generates_placeholder_name_for_null_net_label():
    data = {
        "blocks": [
            {
                "blockId": "block_0002",
                "nets": [
                    {"netNameLabel": None, "connectedLabels": ["SU1D pin G39"]},
                    {"netNameLabel": None, "connectedLabels": ["SU1D pin G40"]},
                ],
                "components": [{"designator": "SU1D", "componentType": "ic"}],
            }
        ]
    }

    result = import_block_semantic(data)

    names = [n.name for n in result.ir.nets]
    assert names == ["net_block_0002_001", "net_block_0002_002"]


def test_import_block_semantic_auto_creates_unknown_component_for_undeclared_designator():
    data = {
        "blocks": [
            {
                "blockId": "block_0001",
                "nets": [
                    {"netNameLabel": "SOME_NET", "connectedLabels": ["Q99 pin 1"]},
                ],
                "components": [],
            }
        ]
    }

    result = import_block_semantic(data)

    q99 = next(c for c in result.ir.components if c.id == "Q99")
    assert q99.type == "unknown"
    assert q99.name == "Q99"
    assert result.ir.nets[0].members == ["Q99:1"]


def test_import_block_semantic_handles_net_missing_connected_labels_key():
    data = {
        "blocks": [
            {"blockId": "block_0001", "nets": [{"netNameLabel": "SOME_NET"}]},
        ]
    }

    result = import_block_semantic(data)

    assert result.ir.nets[0].name == "SOME_NET"
    assert result.ir.nets[0].members == []
