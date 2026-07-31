from dts_gen.core.ir.models import HardwareIR, Relation
from dts_gen.core.pipeline.dts_generator import GenerationScope, generate_dts, rule_supply


def test_generate_dts_returns_empty_text_when_not_implemented():
    ir = HardwareIR(board="board-x", soc="sa8775p")

    result = generate_dts(ir, board="board-x", scope=GenerationScope())

    assert result.dts_text == ""
    assert result.node_sources == []


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
