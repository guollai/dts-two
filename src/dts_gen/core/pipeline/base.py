from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class StageResult(BaseModel):
    ok: bool
    warnings: list[str] = Field(default_factory=list)


class DtsError(BaseModel):
    message: str
    node: str | None = None
    severity: Literal["error", "warning"] = "error"


class FixNote(BaseModel):
    node: str
    change: str
    reason: str
