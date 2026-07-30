from __future__ import annotations

from pydantic import BaseModel, Field

from dts_gen.core.ir.models import HardwareIR, SocMappingEntry


class MappingResult(BaseModel):
    ir: HardwareIR
    mapping_report: list[SocMappingEntry] = Field(default_factory=list)


def map_to_soc(ir: HardwareIR, soc: str) -> MappingResult:
    return MappingResult(ir=ir, mapping_report=[])
