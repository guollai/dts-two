from __future__ import annotations

from pydantic import BaseModel, Field

from dts_gen.core.pipeline.base import DtsError, FixNote


class RepairResult(BaseModel):
    dts_text: str
    applied_fixes: list[FixNote] = Field(default_factory=list)


def repair_dts(dts_text: str, errors: list[DtsError]) -> RepairResult:
    return RepairResult(dts_text=dts_text, applied_fixes=[])
