from __future__ import annotations

from pydantic import BaseModel, Field

from dts_gen.core.ir.models import HardwareIR, NodeSourceRef, UnresolvedItem


class ExplainResult(BaseModel):
    source_refs: list[NodeSourceRef] = Field(default_factory=list)
    rule_ids: list[str] = Field(default_factory=list)
    unresolved: list[UnresolvedItem] = Field(default_factory=list)


def explain_node(ir: HardwareIR, node_path: str) -> ExplainResult:
    matching = [item for item in ir.unresolved if item.field == node_path]
    return ExplainResult(source_refs=[], rule_ids=[], unresolved=matching)
