from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from dts_gen.core.knowledge.binding_repo import BindingRepo
from dts_gen.core.knowledge.device_db import DeviceDb
from dts_gen.core.knowledge.soc_repo import SocRepo
from dts_gen.core.knowledge.style_guide import StyleGuide


@dataclass
class KnowledgeContext:
    soc_repo: SocRepo
    binding_repo: BindingRepo
    device_db: DeviceDb
    style_guide: StyleGuide


def build_knowledge_context(data_dir: Path) -> KnowledgeContext:
    return KnowledgeContext(
        soc_repo=SocRepo(data_dir=data_dir),
        binding_repo=BindingRepo(data_dir=data_dir),
        device_db=DeviceDb(data_dir=data_dir),
        style_guide=StyleGuide(data_dir=data_dir),
    )


def read_soc_dtsi(ctx: KnowledgeContext, soc: str) -> dict:
    return {"soc": soc, "files": ctx.soc_repo.get_reference_dtsi(soc)}


def read_binding(ctx: KnowledgeContext, compatible: str) -> dict:
    schema = ctx.binding_repo.get_schema(compatible)
    if schema is None:
        return {"error": "not_found", "compatible": compatible}
    return schema


def read_device(ctx: KnowledgeContext, part_number: str) -> dict:
    template = ctx.device_db.lookup(part_number)
    if template is None:
        return {"error": "not_found", "part_number": part_number}
    return template


def read_styleguide(ctx: KnowledgeContext) -> dict:
    return {"content": ctx.style_guide.naming_rules()}
