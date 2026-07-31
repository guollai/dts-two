from __future__ import annotations

import re
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


GPIO_ENDPOINT_RE = re.compile(r"^(\w+):gpio(\d+)$")


def parse_gpio_endpoint(endpoint: str | None) -> "tuple[str, int] | None":
    if endpoint is None:
        return None
    match = GPIO_ENDPOINT_RE.match(endpoint)
    if not match:
        return None
    return (match.group(1), int(match.group(2)))


def rule_control_gpio(rel: Relation, ir: HardwareIR) -> "tuple[str, str] | None":
    if rel.property not in ("enable-gpios", "reset-gpios"):
        return None
    if rel.active not in ("high", "low"):
        return None
    gpio_ref = parse_gpio_endpoint(rel.from_)
    if gpio_ref is None:
        return None
    controller, pin = gpio_ref
    flag = "GPIO_ACTIVE_HIGH" if rel.active == "high" else "GPIO_ACTIVE_LOW"
    return (rel.property, f"<&{controller} {pin} {flag}>")


def rule_phy_reference(rel: Relation, ir: HardwareIR) -> "tuple[str, str] | None":
    if rel.kind != "phy-reference":
        return None
    return ("phys", f"<&{rel.to}>")


RULES: dict[str, list[RuleFn]] = {
    "supply": [rule_supply],
    "control": [rule_control_gpio],
    "phy-reference": [rule_phy_reference],
}



class GenerateResult(BaseModel):
    dts_text: str = ""
    node_sources: list[NodeSourceRef] = Field(default_factory=list)


def generate_dts(ir: HardwareIR, board: str | None, scope: GenerationScope) -> GenerateResult:
    return GenerateResult(dts_text="", node_sources=[])
