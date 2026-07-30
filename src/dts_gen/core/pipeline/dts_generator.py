from __future__ import annotations

from pydantic import BaseModel, Field

from dts_gen.core.ir.models import HardwareIR, NodeSourceRef


class GenerationScope(BaseModel):
    subsystem: str | None = None


class GenerateResult(BaseModel):
    dts_text: str = ""
    node_sources: list[NodeSourceRef] = Field(default_factory=list)


def generate_dts(ir: HardwareIR, board: str | None, scope: GenerationScope) -> GenerateResult:
    return GenerateResult(dts_text="", node_sources=[])
