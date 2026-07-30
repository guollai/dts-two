from __future__ import annotations

from pydantic import BaseModel, Field

from dts_gen.core.pipeline.base import DtsError


class ValidateResult(BaseModel):
    errors: list[DtsError] = Field(default_factory=list)
    warnings: list[DtsError] = Field(default_factory=list)


def validate_dts(dts_text: str, target_platform: str | None = None) -> ValidateResult:
    return ValidateResult(
        errors=[],
        warnings=[
            DtsError(
                message="validator stage not implemented yet; dtc/dtbs_check were not run",
                node=None,
                severity="warning",
            )
        ],
    )
