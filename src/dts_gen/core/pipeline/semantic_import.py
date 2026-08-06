from __future__ import annotations

import re

from pydantic import BaseModel, Field

from dts_gen.core.ir.models import Component, HardwareIR, Net, UnresolvedItem

# "R3 pin 1" / "SU1C pin G37" / "Q54 pin D" / "R544 pin2"（无空格变体）
_LABEL_RE = re.compile(r"^([A-Za-z0-9_\-\.\?]+)\s*pin\s*([A-Za-z0-9]+)$", re.IGNORECASE)
# 跨页引用条目，如 "[22]"、"[7,37,8]"、"[47-C4,47-D4]"
_BRACKET_RE = re.compile(r"^\[.*\]$")


def parse_connected_label(label: str) -> tuple[str, str] | None:
    stripped = label.strip()
    if _BRACKET_RE.match(stripped):
        return None
    match = _LABEL_RE.match(stripped)
    if not match:
        return None
    designator, pin = match.groups()
    if "?" in designator:
        return None
    return (designator, pin)


class ImportResult(BaseModel):
    ir: HardwareIR
    unresolved: list[UnresolvedItem] = Field(default_factory=list)


def import_block_semantic(data: dict, page: int | None = None) -> ImportResult:
    components: dict[str, Component] = {}
    unresolved: list[UnresolvedItem] = []

    for block in data.get("blocks", []):
        block_id = block.get("blockId", "unknown_block")
        for comp in block.get("components", []):
            designator = comp.get("designator")
            component_type = comp.get("componentType")
            if designator is None or component_type is None:
                unresolved.append(
                    UnresolvedItem(
                        field=f"component:{block_id}",
                        reason=f"组件缺少 designator 或 componentType 字段: {comp!r}",
                        page=page,
                    )
                )
                continue
            components[designator] = Component(id=designator, type=component_type, name=designator)

    nets: list[Net] = []
    for block in data.get("blocks", []):
        block_id = block.get("blockId", "unknown_block")
        for net_seq, net_entry in enumerate(block.get("nets", []), start=1):
            name = net_entry.get("netNameLabel") or f"net_{block_id}_{net_seq:03d}"
            members: list[str] = []
            for label in net_entry.get("connectedLabels", []):
                parsed = parse_connected_label(label)
                if parsed is None:
                    if "pin" in label.lower() and not _BRACKET_RE.match(label.strip()):
                        unresolved.append(
                            UnresolvedItem(
                                field=f"net:{name}",
                                reason=f"无法解析连接标签: {label!r}",
                                page=page,
                            )
                        )
                    continue
                designator, pin = parsed
                if designator not in components:
                    components[designator] = Component(id=designator, type="unknown", name=designator)
                members.append(f"{designator}:{pin}")
            nets.append(Net(name=name, members=members))

    ir = HardwareIR(components=list(components.values()), nets=nets, unresolved=unresolved)
    return ImportResult(ir=ir, unresolved=unresolved)

