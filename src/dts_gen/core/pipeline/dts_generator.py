from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from pydantic import BaseModel, Field

from dts_gen.core.ir.models import HardwareIR, NodeSourceRef, Relation, UnresolvedItem


class GenerationScope(BaseModel):
    subsystem: str | None = None


@dataclass
class DtsProperty:
    name: str
    value: str
    rule_id: str
    source_relation: Relation | None = None


@dataclass
class DtsNode:
    label: str
    properties: list[DtsProperty] = field(default_factory=list)
    component_id: str | None = None

    def add_property(
        self, name: str, value: str, rule_id: str, relation: Relation | None = None
    ) -> None:
        self.properties.append(DtsProperty(name, value, rule_id, relation))


RuleFn = Callable[[Relation, HardwareIR], "tuple[str, str] | None"]


def rule_supply(rel: Relation, ir: HardwareIR) -> "tuple[str, str] | None":
    if rel.property is None or rel.from_ is None:
        return None
    return (rel.property, f"<&{rel.from_}>")


class GenerateResult(BaseModel):
    dts_text: str = ""
    node_sources: list[NodeSourceRef] = Field(default_factory=list)


def generate_dts(ir: HardwareIR, board: str | None, scope: GenerationScope) -> GenerateResult:
    return GenerateResult(dts_text="", node_sources=[])
