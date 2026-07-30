from __future__ import annotations

from pydantic import BaseModel, Field


class Component(BaseModel):
    id: str
    type: str
    name: str


class Endpoint(BaseModel):
    component_id: str
    pin_name: str
    signal_type: str | None = None
    pair: str | None = None
    direction: str | None = None
    function: str | None = None
    polarity: str | None = None
    impedance: str | None = None
    drive_strength: str | None = None
    confidence: float
    source: str


class Net(BaseModel):
    name: str
    members: list[str] = Field(default_factory=list)
    signal_type: str | None = None
    pull: str | None = None


class Relation(BaseModel):
    kind: str
    from_: str | None = Field(default=None, alias="from")
    to: str | None = None
    bus: str | None = None
    device: str | None = None
    property: str | None = None
    active: str | None = None
    net: str | None = None

    model_config = {"populate_by_name": True}


class PinctrlGroup(BaseModel):
    name: str
    function: str
    pins: list[str] = Field(default_factory=list)
    drive_strength: str | None = None
    bias: str | None = None


class SocMappingEntry(BaseModel):
    role: str
    mapped_to: str
    confidence: float


class UnresolvedItem(BaseModel):
    field: str
    reason: str
    page: int | None = None


class NodeSourceRef(BaseModel):
    node: str
    source_page: int | None = None
    component_id: str | None = None
    rule_id: str | None = None


class HardwareIR(BaseModel):
    board: str | None = None
    soc: str | None = None
    components: list[Component] = Field(default_factory=list)
    nets: list[Net] = Field(default_factory=list)
    relations: list[Relation] = Field(default_factory=list)
    pinctrl_groups: list[PinctrlGroup] = Field(default_factory=list)
    soc_mapping: list[SocMappingEntry] = Field(default_factory=list)
    endpoints: list[Endpoint] = Field(default_factory=list)
    unresolved: list[UnresolvedItem] = Field(default_factory=list)
