from __future__ import annotations

from pydantic import BaseModel, Field

from dts_gen.core.ir.models import HardwareIR, UnresolvedItem
from dts_gen.core.pipeline.input_parser import PageAsset


class ExtractResult(BaseModel):
    ir: HardwareIR
    unresolved: list[UnresolvedItem] = Field(default_factory=list)


def extract_hardware_graph(
    pages: list[PageAsset], page_range: tuple[int, int] | None = None
) -> ExtractResult:
    start_page = page_range[0] if page_range else (pages[0].page_number if pages else None)
    return ExtractResult(
        ir=HardwareIR(),
        unresolved=[
            UnresolvedItem(
                field="*",
                reason="hardware_extractor stage not implemented yet; no components were identified",
                page=start_page,
            )
        ],
    )
