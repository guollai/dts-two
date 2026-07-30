from dts_gen.core.ir.models import HardwareIR
from dts_gen.core.pipeline.dts_generator import GenerationScope, generate_dts


def test_generate_dts_returns_empty_text_when_not_implemented():
    ir = HardwareIR(board="board-x", soc="sa8775p")

    result = generate_dts(ir, board="board-x", scope=GenerationScope())

    assert result.dts_text == ""
    assert result.node_sources == []


def test_generation_scope_defaults_subsystem_to_none():
    scope = GenerationScope()

    assert scope.subsystem is None
