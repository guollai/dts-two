from dts_gen.core.ir.models import (
    Component,
    Endpoint,
    HardwareIR,
    Net,
    NodeSourceRef,
    PinctrlGroup,
    Relation,
    SocMappingEntry,
    UnresolvedItem,
)


def test_hardware_ir_round_trip_json():
    ir = HardwareIR(
        board="board-x",
        soc="sa8775p",
        components=[Component(id="soc_usb0", type="usb-controller", name="dwc3")],
        nets=[Net(name="USB0_HS_DP", members=["soc_usb0:dp", "redriver0:dp"])],
        relations=[
            Relation(
                kind="control",
                from_="soc_tlmm:gpio23",
                to="redriver0",
                property="enable-gpios",
                active="high",
            )
        ],
        pinctrl_groups=[
            PinctrlGroup(name="usb0_default", function="gpio", pins=["gpio23"])
        ],
        soc_mapping=[SocMappingEntry(role="usb-controller", mapped_to="usb_0", confidence=0.95)],
        endpoints=[
            Endpoint(
                component_id="redriver0",
                pin_name="dp",
                signal_type="hs",
                pair="dp",
                direction="bidirectional",
                function="usb2_dp",
                polarity="positive",
                impedance="90ohm-diff",
                drive_strength=None,
                confidence=0.92,
                source="schematic:page12",
            )
        ],
        unresolved=[UnresolvedItem(field="redriver0.vcc-supply", reason="连线不清晰", page=12)],
    )

    dumped = ir.model_dump_json()
    restored = HardwareIR.model_validate_json(dumped)

    assert restored.board == "board-x"
    assert restored.components[0].id == "soc_usb0"
    assert restored.relations[0].from_ == "soc_tlmm:gpio23"
    assert restored.endpoints[0].confidence == 0.92
    assert restored.unresolved[0].page == 12


def test_hardware_ir_defaults_to_empty_collections():
    ir = HardwareIR(board=None, soc=None)

    assert ir.components == []
    assert ir.nets == []
    assert ir.relations == []
    assert ir.pinctrl_groups == []
    assert ir.soc_mapping == []
    assert ir.endpoints == []
    assert ir.unresolved == []


def test_node_source_ref_optional_fields_default_none():
    ref = NodeSourceRef(node="&usb_0")

    assert ref.source_page is None
    assert ref.component_id is None
    assert ref.rule_id is None


def test_relation_from_field_uses_from_alias_in_json():
    """Verify that Relation.from_ field correctly aliases to 'from' in JSON."""
    # Test 1: Construct from dict with literal "from" key
    relation = Relation.model_validate(
        {"kind": "control", "from": "soc_tlmm:gpio23", "to": "redriver0"}
    )
    assert relation.from_ == "soc_tlmm:gpio23"

    # Test 2: Dump with by_alias=True produces literal "from" key
    dumped = relation.model_dump(by_alias=True)
    assert "from" in dumped
    assert dumped["from"] == "soc_tlmm:gpio23"
    assert "from_" not in dumped

    # Test 3: Round-trip via JSON with by_alias=True
    json_str = relation.model_dump_json(by_alias=True)
    assert '"from"' in json_str
    assert '"from_"' not in json_str
    restored = Relation.model_validate_json(json_str)
    assert restored.from_ == "soc_tlmm:gpio23"
