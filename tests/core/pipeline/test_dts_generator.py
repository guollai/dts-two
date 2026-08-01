from dts_gen.core.ir.models import Component, HardwareIR, Relation
from dts_gen.core.pipeline.dts_generator import (
    RULES,
    DtsNode,
    GenerationScope,
    build_node_sources,
    build_nodes,
    generate_dts,
    parse_gpio_endpoint,
    rule_control_gpio,
    rule_phy_reference,
    rule_supply,
    serialize_dts,
    serialize_node,
)


def test_generate_dts_returns_empty_text_for_ir_without_components():
    ir = HardwareIR(board="board-x", soc="sa8775p")

    result = generate_dts(ir, board="board-x", scope=GenerationScope())

    assert result.dts_text == ""
    assert result.node_sources == []
    assert result.unresolved == []


def test_generation_scope_defaults_subsystem_to_none():
    scope = GenerationScope()

    assert scope.subsystem is None


def test_rule_supply_returns_property_and_phandle_reference():
    rel = Relation(kind="supply", from_="pmic_ldo3", to="usb_ctrl0", property="vbus-supply")
    ir = HardwareIR()

    result = rule_supply(rel, ir)

    assert result == ("vbus-supply", "<&pmic_ldo3>")


def test_rule_supply_returns_none_when_property_missing():
    rel = Relation(kind="supply", from_="pmic_ldo3", to="usb_ctrl0")
    ir = HardwareIR()

    assert rule_supply(rel, ir) is None


def test_rule_supply_returns_none_when_from_missing():
    rel = Relation(kind="supply", to="usb_ctrl0", property="vbus-supply")
    ir = HardwareIR()

    assert rule_supply(rel, ir) is None


def test_parse_gpio_endpoint_extracts_controller_and_pin():
    assert parse_gpio_endpoint("soc_tlmm:gpio23") == ("soc_tlmm", 23)


def test_parse_gpio_endpoint_returns_none_for_malformed_string():
    assert parse_gpio_endpoint("soc_tlmm-gpio23") is None
    assert parse_gpio_endpoint(None) is None


def test_rule_control_gpio_returns_active_high_reference():
    rel = Relation(
        kind="control",
        from_="soc_tlmm:gpio23",
        to="redriver0",
        property="enable-gpios",
        active="high",
    )
    ir = HardwareIR()

    result = rule_control_gpio(rel, ir)

    assert result == ("enable-gpios", "<&soc_tlmm 23 GPIO_ACTIVE_HIGH>")


def test_rule_control_gpio_returns_active_low_reference():
    rel = Relation(
        kind="control",
        from_="soc_tlmm:gpio5",
        to="redriver0",
        property="reset-gpios",
        active="low",
    )
    ir = HardwareIR()

    result = rule_control_gpio(rel, ir)

    assert result == ("reset-gpios", "<&soc_tlmm 5 GPIO_ACTIVE_LOW>")


def test_rule_control_gpio_returns_none_for_unknown_property():
    rel = Relation(
        kind="control",
        from_="soc_tlmm:gpio23",
        to="redriver0",
        property="unknown-prop",
        active="high",
    )
    ir = HardwareIR()

    assert rule_control_gpio(rel, ir) is None


def test_rule_control_gpio_returns_none_for_malformed_from_endpoint():
    rel = Relation(
        kind="control",
        from_="soc_tlmm-gpio23",
        to="redriver0",
        property="enable-gpios",
        active="high",
    )
    ir = HardwareIR()

    assert rule_control_gpio(rel, ir) is None


def test_rule_control_gpio_returns_none_for_missing_active():
    rel = Relation(
        kind="control",
        from_="soc_tlmm:gpio23",
        to="redriver0",
        property="enable-gpios",
    )
    ir = HardwareIR()

    assert rule_control_gpio(rel, ir) is None


def test_rule_phy_reference_returns_phys_property():
    rel = Relation(kind="phy-reference", from_="redriver0", to="usb_phy0")
    ir = HardwareIR()

    result = rule_phy_reference(rel, ir)

    assert result == ("phys", "<&usb_phy0>")


def test_rule_phy_reference_returns_none_for_wrong_kind():
    rel = Relation(kind="supply", from_="redriver0", to="usb_phy0")
    ir = HardwareIR()

    assert rule_phy_reference(rel, ir) is None


def test_rule_phy_reference_returns_none_when_to_missing():
    rel = Relation(kind="phy-reference", from_="usb_ctrl0")
    ir = HardwareIR()

    assert rule_phy_reference(rel, ir) is None


def test_rules_table_maps_all_three_kinds():
    assert set(RULES.keys()) == {"supply", "control", "phy-reference"}
    assert RULES["supply"] == [rule_supply]
    assert RULES["control"] == [rule_control_gpio]
    assert RULES["phy-reference"] == [rule_phy_reference]


def test_build_nodes_creates_one_node_per_component():
    ir = HardwareIR(
        components=[
            Component(id="usb_ctrl0", type="usb-controller", name="dwc3"),
            Component(id="pmic_ldo3", type="regulator", name="ldo3"),
        ],
    )

    nodes, unresolved = build_nodes(ir)

    labels = sorted(n.label for n in nodes)
    assert labels == ["pmic_ldo3", "usb_ctrl0"]
    assert unresolved == []


def test_build_nodes_applies_supply_rule_to_target_node():
    ir = HardwareIR(
        components=[
            Component(id="usb_ctrl0", type="usb-controller", name="dwc3"),
            Component(id="pmic_ldo3", type="regulator", name="ldo3"),
        ],
        relations=[
            Relation(kind="supply", from_="pmic_ldo3", to="usb_ctrl0", property="vbus-supply"),
        ],
    )

    nodes, unresolved = build_nodes(ir)

    usb_node = next(n for n in nodes if n.label == "usb_ctrl0")
    assert len(usb_node.properties) == 1
    assert usb_node.properties[0].name == "vbus-supply"
    assert usb_node.properties[0].value == "<&pmic_ldo3>"
    assert usb_node.properties[0].rule_id == "rule_supply"
    assert unresolved == []


def test_build_nodes_applies_phy_reference_rule_to_from_node():
    ir = HardwareIR(
        components=[
            Component(id="usb_ctrl0", type="usb-controller", name="dwc3"),
            Component(id="usb_phy0", type="usb-phy", name="qcom-usb3-phy"),
        ],
        relations=[
            Relation(kind="phy-reference", from_="usb_ctrl0", to="usb_phy0"),
        ],
    )

    nodes, unresolved = build_nodes(ir)

    ctrl_node = next(n for n in nodes if n.label == "usb_ctrl0")
    assert ctrl_node.properties[0].name == "phys"
    assert ctrl_node.properties[0].value == "<&usb_phy0>"


def test_build_nodes_reports_unresolved_for_missing_target_component():
    ir = HardwareIR(
        components=[Component(id="pmic_ldo3", type="regulator", name="ldo3")],
        relations=[
            Relation(kind="supply", from_="pmic_ldo3", to="usb_ctrl0", property="vbus-supply"),
        ],
    )

    nodes, unresolved = build_nodes(ir)

    assert len(unresolved) == 1
    assert "usb_ctrl0" in unresolved[0].reason


def test_build_nodes_reports_unresolved_for_unmatched_rule():
    ir = HardwareIR(
        components=[Component(id="redriver0", type="usb-redriver", name="tusb2e11")],
        relations=[
            Relation(kind="control", from_="soc_tlmm:gpio23", to="redriver0", property="unknown-prop"),
        ],
    )

    nodes, unresolved = build_nodes(ir)

    assert len(unresolved) == 1
    redriver_node = next(n for n in nodes if n.label == "redriver0")
    assert redriver_node.properties == []


def test_build_nodes_reports_unresolved_for_phy_reference_missing_to():
    ir = HardwareIR(
        components=[Component(id="usb_ctrl0", type="usb-controller", name="dwc3")],
        relations=[Relation(kind="phy-reference", from_="usb_ctrl0")],
    )

    nodes, unresolved = build_nodes(ir)

    assert len(unresolved) == 1
    ctrl_node = next(n for n in nodes if n.label == "usb_ctrl0")
    assert ctrl_node.properties == []


def test_build_nodes_reports_unresolved_for_supply_with_nonexistent_regulator():
    ir = HardwareIR(
        components=[Component(id="usb_ctrl0", type="usb-controller", name="dwc3")],
        relations=[
            Relation(kind="supply", from_="typo_regulator", to="usb_ctrl0", property="vbus-supply"),
        ],
    )

    nodes, unresolved = build_nodes(ir)

    assert len(unresolved) == 1
    usb_node = next(n for n in nodes if n.label == "usb_ctrl0")
    assert usb_node.properties == []


def test_build_nodes_reports_unresolved_for_phy_reference_with_nonexistent_phy():
    ir = HardwareIR(
        components=[Component(id="usb_ctrl0", type="usb-controller", name="dwc3")],
        relations=[
            Relation(kind="phy-reference", from_="usb_ctrl0", to="usb_phy_nonexistent"),
        ],
    )

    nodes, unresolved = build_nodes(ir)

    assert len(unresolved) == 1
    ctrl_node = next(n for n in nodes if n.label == "usb_ctrl0")
    assert ctrl_node.properties == []


def test_build_nodes_still_accepts_valid_supply_and_phy_reference():
    # Regression guard: the new referenced-component check must not break the
    # normal case where the referenced component genuinely exists.
    ir = HardwareIR(
        components=[
            Component(id="usb_ctrl0", type="usb-controller", name="dwc3"),
            Component(id="usb_phy0", type="usb-phy", name="qcom-usb3-phy"),
            Component(id="pmic_ldo3", type="regulator", name="ldo3"),
        ],
        relations=[
            Relation(kind="supply", from_="pmic_ldo3", to="usb_ctrl0", property="vbus-supply"),
            Relation(kind="phy-reference", from_="usb_ctrl0", to="usb_phy0"),
        ],
    )

    nodes, unresolved = build_nodes(ir)

    assert unresolved == []
    ctrl_node = next(n for n in nodes if n.label == "usb_ctrl0")
    assert len(ctrl_node.properties) == 2


def test_build_nodes_handles_empty_relations():
    ir = HardwareIR(components=[Component(id="usb_ctrl0", type="usb-controller", name="dwc3")])

    nodes, unresolved = build_nodes(ir)

    assert len(nodes) == 1
    assert nodes[0].properties == []
    assert unresolved == []


def test_serialize_node_skips_nodes_without_properties():
    node = DtsNode(label="pmic_ldo3", component_id="pmic_ldo3")

    assert serialize_dts([node]) == ""


def test_serialize_node_renders_status_and_properties():
    node = DtsNode(label="usb_ctrl0", component_id="usb_ctrl0")
    node.add_property("vbus-supply", "<&pmic_ldo3>", rule_id="rule_supply")

    text = serialize_node(node)

    assert text == '&usb_ctrl0 {\n    status = "okay";\n    vbus-supply = <&pmic_ldo3>;\n};'


def test_serialize_dts_joins_multiple_nodes_with_blank_line():
    node_a = DtsNode(label="usb_ctrl0", component_id="usb_ctrl0")
    node_a.add_property("vbus-supply", "<&pmic_ldo3>", rule_id="rule_supply")
    node_b = DtsNode(label="redriver0", component_id="redriver0")
    node_b.add_property("enable-gpios", "<&soc_tlmm 23 GPIO_ACTIVE_HIGH>", rule_id="rule_control_gpio")

    text = serialize_dts([node_a, node_b])

    assert "\n\n" in text
    assert text.count("&usb_ctrl0") == 1
    assert text.count("&redriver0") == 1


def test_build_node_sources_extracts_rule_id_and_component_id():
    node = DtsNode(label="usb_ctrl0", component_id="usb_ctrl0")
    node.add_property("vbus-supply", "<&pmic_ldo3>", rule_id="rule_supply")

    sources = build_node_sources([node])

    assert len(sources) == 1
    assert sources[0].node == "&usb_ctrl0"
    assert sources[0].component_id == "usb_ctrl0"
    assert sources[0].rule_id == "rule_supply"


def test_generate_dts_end_to_end_usb_topology():
    ir = HardwareIR(
        board="hamoa-evb", soc="hamoa",
        components=[
            Component(id="usb_ctrl0", type="usb-controller", name="dwc3"),
            Component(id="usb_phy0", type="usb-phy", name="qcom-usb3-phy"),
            Component(id="redriver0", type="usb-redriver", name="tusb2e11"),
            Component(id="connector0", type="usb-connector", name="typec"),
            Component(id="pmic_ldo3", type="regulator", name="ldo3"),
        ],
        relations=[
            Relation(kind="supply", from_="pmic_ldo3", to="usb_ctrl0", property="vbus-supply"),
            Relation(kind="control", from_="soc_tlmm:gpio23", to="redriver0", property="enable-gpios", active="high"),
            Relation(kind="phy-reference", from_="usb_ctrl0", to="usb_phy0"),
        ],
    )

    result = generate_dts(ir, board="hamoa-evb", scope=GenerationScope())

    assert "&usb_ctrl0" in result.dts_text
    assert "vbus-supply = <&pmic_ldo3>;" in result.dts_text
    assert "phys = <&usb_phy0>;" in result.dts_text
    assert "&redriver0" in result.dts_text
    assert "enable-gpios = <&soc_tlmm 23 GPIO_ACTIVE_HIGH>;" in result.dts_text
    assert "&usb_phy0 {" not in result.dts_text
    assert "&connector0" not in result.dts_text
    assert "&pmic_ldo3 {" not in result.dts_text
    assert len(result.node_sources) == 3
    assert result.unresolved == []


def test_generate_dts_returns_unresolved_when_relation_target_missing():
    ir = HardwareIR(
        components=[Component(id="pmic_ldo3", type="regulator", name="ldo3")],
        relations=[Relation(kind="supply", from_="pmic_ldo3", to="usb_ctrl0", property="vbus-supply")],
    )

    result = generate_dts(ir, board=None, scope=GenerationScope())

    assert result.dts_text == ""
    assert len(result.unresolved) == 1
