from __future__ import annotations

import difflib

from pydantic import BaseModel, Field


class DiffResult(BaseModel):
    patch: str
    risk_notes: list[str] = Field(default_factory=list)


def diff_dts(original: str, generated: str, scope: str | None = None) -> DiffResult:
    diff_lines = list(
        difflib.unified_diff(
            original.splitlines(keepends=True),
            generated.splitlines(keepends=True),
            fromfile="existing.dts",
            tofile="generated.dts",
        )
    )
    return DiffResult(patch="".join(diff_lines), risk_notes=[])
