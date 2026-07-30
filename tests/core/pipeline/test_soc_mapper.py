from dts_gen.core.ir.models import Component, HardwareIR
from dts_gen.core.pipeline.soc_mapper import map_to_soc


def test_map_to_soc_returns_ir_unchanged_and_empty_report():
    ir = HardwareIR(
        board="board-x",
        soc="sa8775p",
        components=[Component(id="soc_usb0", type="usb-controller", name="dwc3")],
    )

    result = map_to_soc(ir, soc="sa8775p")

    assert result.ir.components == ir.components
    assert result.mapping_report == []
